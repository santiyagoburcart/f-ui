from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action # Added for custom actions
from django.shortcuts import get_object_or_404
from .models import Server, XrayUser, AlertRule, Notification
from .serializers import ServerSerializer, XrayUserSerializer, AlertRuleSerializer, NotificationSerializer
from .xray_client import XrayClient
import logging
import json # For VLESS link generation (if params are complex)
import base64 # For some config formats

logger = logging.getLogger(__name__)

class ServerViewSet(viewsets.ModelViewSet):
    queryset = Server.objects.all()
    serializer_class = ServerSerializer

class XrayUserViewSet(viewsets.ModelViewSet):
    queryset = XrayUser.objects.all()
    serializer_class = XrayUserSerializer

    def perform_create(self, serializer):
        xray_user_instance = serializer.save()
        logger.info(f"XrayUser {xray_user_instance.email} saved to panel DB (id: {xray_user_instance.id}).")
        server_instance = xray_user_instance.server
        if not server_instance:
            logger.error(f"Cannot add user to Xray: Server instance not found for user {xray_user_instance.email}.")
            xray_user_instance.enable = False
            xray_user_instance.settings_json = {"error": "Panel DB Error: Server not found for user"}
            xray_user_instance.save(update_fields=['enable', 'settings_json'])
            return
        logger.info(f"Attempting to add user {xray_user_instance.email} to Xray server {server_instance.name} ({server_instance.address}).")

        client_inbound_tag_for_user_operations = getattr(server_instance, 'api_inbound_tag', None)
        if not client_inbound_tag_for_user_operations:
            logger.warning(f"Server {server_instance.name} does not have 'api_inbound_tag' defined. Operations on Xray might fail or use client's default tag.")

        client = XrayClient(
            server_address=server_instance.address,
            server_port=server_instance.port,
            api_token=server_instance.api_token,
            inbound_tag=client_inbound_tag_for_user_operations
        )

        if not client.is_connected():
            logger.error(f"Failed to connect to Xray server {server_instance.name} for adding user {xray_user_instance.email}.")
            xray_user_instance.enable = False
            xray_user_instance.settings_json = {"error": "Failed to add to Xray server: connection failed"}
            xray_user_instance.save(update_fields=['enable', 'settings_json'])
            return

        try:
            if not xray_user_instance.protocol:
                logger.warning(f"User {xray_user_instance.email} has no protocol defined. Using 'vless' as default for Xray add.")
                xray_user_instance.protocol = "vless" # Default protocol
            add_success = client.add_user(
                email=xray_user_instance.email,
                user_uuid=str(xray_user_instance.uuid),
                protocol=xray_user_instance.protocol,
                level=getattr(xray_user_instance, 'level', 0)
            )

            if add_success:
                logger.info(f"User {xray_user_instance.email} successfully requested to be added to Xray server {server_instance.name}.")
                xray_user_instance.settings_json = {"status_on_xray": "added_successfully"}
            else:
                logger.error(f"Failed to add user {xray_user_instance.email} to Xray server {server_instance.name} (client.add_user returned False).")
                xray_user_instance.enable = False # If add failed on Xray, reflect in panel DB
                xray_user_instance.settings_json = {"error": "Failed to add to Xray server: client command failed"}
            xray_user_instance.save(update_fields=['enable', 'settings_json', 'protocol'])

        except Exception as e:
            logger.error(f"Exception during add_user for {xray_user_instance.email} on Xray server {server_instance.name}: {e}", exc_info=True)
            xray_user_instance.enable = False
            xray_user_instance.settings_json = {"error": f"Exception during add to Xray: {str(e)}"}
            xray_user_instance.save(update_fields=['enable', 'settings_json'])
        finally:
            if client: client.close()

    def perform_update(self, serializer):
        original_instance = self.get_object()
        original_enable_status = original_instance.enable

        updated_instance = serializer.save()
        logger.info(f"XrayUser {updated_instance.email} updated in panel DB.")

        new_enable_status = updated_instance.enable
        enable_field_changed = 'enable' in serializer.validated_data and original_enable_status != new_enable_status

        if enable_field_changed:
            logger.info(f"Enable status for user {updated_instance.email} changed from {original_enable_status} to {new_enable_status}. Syncing with Xray server.")

            server_instance = updated_instance.server
            if not server_instance:
                logger.error(f"Server instance not found for user {updated_instance.email}. Cannot sync enable/disable with Xray.")
                updated_instance.settings_json = {"error": "Panel DB Error: Server not found for user, Xray sync failed"}
                updated_instance.save(update_fields=['settings_json'])
                return

            client_inbound_tag = getattr(server_instance, 'api_inbound_tag', None)
            client = XrayClient(
                server_address=server_instance.address,
                server_port=server_instance.port,
                api_token=server_instance.api_token,
                inbound_tag=client_inbound_tag
            )

            if not client.is_connected():
                logger.error(f"Failed to connect to Xray server {server_instance.name} for syncing enable/disable status of {updated_instance.email}.")
                updated_instance.settings_json = {"error": "Xray sync failed: connection error"}
                # Revert change in DB if Xray sync fails?
                # updated_instance.enable = original_enable_status
                # updated_instance.save(update_fields=['enable', 'settings_json'])
                return

            try:
                sync_successful = False
                if new_enable_status: # If user is being enabled
                    logger.info(f"Attempting to re-add (enable) user {updated_instance.email} on Xray server {server_instance.name}.")
                    if not updated_instance.protocol: # Ensure protocol for add_user
                        updated_instance.protocol = "vless" # Default if not set
                    sync_successful = client.add_user(
                        email=updated_instance.email,
                        user_uuid=str(updated_instance.uuid),
                        protocol=updated_instance.protocol,
                        level=getattr(updated_instance, 'level', 0)
                    )
                    if sync_successful:
                        logger.info(f"User {updated_instance.email} successfully re-added/enabled on Xray server.")
                        updated_instance.settings_json = {"status_on_xray": "enabled"}
                    else:
                        logger.error(f"Failed to re-add/enable user {updated_instance.email} on Xray server.")
                        updated_instance.settings_json = {"error": "Xray sync failed: enable command failed"}
                else: # If user is being disabled
                    logger.info(f"Attempting to remove (disable) user {updated_instance.email} from Xray server {server_instance.name}.")
                    sync_successful = client.remove_user(email=updated_instance.email)
                    if sync_successful:
                        logger.info(f"User {updated_instance.email} successfully removed/disabled from Xray server.")
                        updated_instance.settings_json = {"status_on_xray": "disabled_removed"}
                    else:
                        logger.error(f"Failed to remove/disable user {updated_instance.email} from Xray server.")
                        updated_instance.settings_json = {"error": "Xray sync failed: disable command failed"}

                if not sync_successful:
                    # If Xray operation failed, revert the 'enable' status in the database to maintain consistency
                    logger.warning(f"Reverting 'enable' status for {updated_instance.email} in panel DB due to Xray sync failure.")
                    updated_instance.enable = original_enable_status

                updated_instance.save(update_fields=['enable', 'settings_json', 'protocol']) # protocol might be updated if default was set

            except Exception as e:
                logger.error(f"Exception during Xray sync for enable/disable of user {updated_instance.email}: {e}", exc_info=True)
                updated_instance.settings_json = {"error": f"Xray sync exception: {str(e)}"}
                # Revert 'enable' status
                updated_instance.enable = original_enable_status
                updated_instance.save(update_fields=['enable', 'settings_json'])
            finally:
                if client: client.close()
        else:
            logger.info(f"User {updated_instance.email} updated. 'enable' status was not changed or not part of the request.")


    def perform_destroy(self, instance):
        logger.info(f"Attempting to delete user {instance.email} from panel DB and Xray server.")
        server_instance = instance.server
        deletion_error_on_xray = False
        client_inbound_tag_for_user_operations = getattr(server_instance, 'api_inbound_tag', None)
        if server_instance:
            logger.info(f"Removing user {instance.email} from Xray server {server_instance.name} ({server_instance.address}).")
            client = XrayClient(
                server_address=server_instance.address,
                server_port=server_instance.port,
                api_token=server_instance.api_token,
                inbound_tag=client_inbound_tag_for_user_operations
            )
            if client.is_connected():
                try:
                    remove_success = client.remove_user(email=instance.email)
                    if remove_success:
                        logger.info(f"User {instance.email} successfully requested to be removed from Xray server {server_instance.name}.")
                    else:
                        logger.error(f"Failed to remove user {instance.email} from Xray server {server_instance.name} (client.remove_user returned False).")
                        deletion_error_on_xray = True
                except Exception as e:
                    logger.error(f"Exception during remove_user for {instance.email} on Xray server {server_instance.name}: {e}", exc_info=True)
                    deletion_error_on_xray = True
                finally:
                    if client: client.close()
            else:
                logger.error(f"Failed to connect to Xray server {server_instance.name} for removing user {instance.email}.")
                deletion_error_on_xray = True
        else:
            logger.warning(f"No server instance found for user {instance.email}. Cannot remove from Xray server.")

        if deletion_error_on_xray:
            # If Xray removal fails, we still proceed to delete from the panel DB,
            # but log the error. Depending on requirements, this behavior might change
            # (e.g., prevent deletion if Xray removal fails).
            logger.error(f"User {instance.email} was NOT successfully removed from Xray server. DB record will still be deleted.")

        instance.delete()
        logger.info(f"User {instance.email} deleted from panel DB.")

    @action(detail=True, methods=['get'], name='Generate Config Link')
    def generate_config_link(self, request, pk=None):
        user = self.get_object()
        server = user.server

        if not server:
            logger.warning(f"User {user.email} (PK: {pk}) has no server associated.")
            return Response({"error": "User is not associated with a server."}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"Generating config link for user {user.email} on server {server.name}")

        # These would ideally come from Server model fields or a more structured config source
        # For now, using placeholders or common defaults.
        # Ensure these attributes exist on your Server model or provide fallbacks
        network_type = getattr(server, 'config_network', 'tcp')
        security_type = getattr(server, 'config_security', 'none')
        path_param = getattr(server, 'config_path', '/') if network_type in ['ws', 'grpc'] else ''
        host_sni = getattr(server, 'config_sni', server.address) if security_type == 'tls' else ''
        public_port = getattr(server, 'public_port', server.port if network_type == 'tcp' else (443 if security_type == 'tls' else 80) )
        remarks = user.email

        if user.protocol.lower() == 'vless':
            link_uuid = str(user.uuid)
            link_address = server.address

            params = {}
            if network_type: params['type'] = network_type
            if security_type: params['security'] = security_type
            if path_param and network_type in ['ws', 'grpc']: params['path'] = path_param
            if host_sni and security_type == 'tls': params['host'] = host_sni
            # 'flow' parameter might be needed for some VLESS configurations
            flow_param = getattr(user, 'flow_setting', None) or getattr(server, 'default_flow', None)
            if flow_param: params['flow'] = flow_param

            query_string = "&".join([f"{k}={v}" for k, v in params.items() if v])

            config_link = f"vless://{link_uuid}@{link_address}:{public_port}"
            if query_string:
                config_link += f"?{query_string}"
            config_link += f"#{remarks}"

            logger.info(f"Generated VLESS link for {user.email}: {config_link}")
            return Response({"config_link": config_link, "protocol": "vless"}, status=status.HTTP_200_OK)

        elif user.protocol.lower() == 'vmess':
            vmess_config = {
                "v": "2",
                "ps": remarks,
                "add": server.address,
                "port": str(public_port),
                "id": str(user.uuid),
                "aid": "0",
                "net": network_type,
                "type": "none", # Default for TCP, adjust if other types are primary for VMess
                "host": host_sni if network_type == 'ws' else "",
                "path": path_param if network_type == 'ws' else "",
                "tls": security_type
            }
            if network_type != 'ws': # Clean up ws-specific fields if not using ws
                vmess_config.pop('host', None)
                vmess_config.pop('path', None)

            config_link = "vmess://" + base64.b64encode(json.dumps(vmess_config, sort_keys=True).encode('utf-8')).decode('utf-8')
            logger.info(f"Generated VMess link for {user.email}: {config_link}")
            return Response({"config_link": config_link, "protocol": "vmess", "details": vmess_config }, status=status.HTTP_200_OK)

        else:
            logger.warning(f"Link generation for protocol '{user.protocol}' is not yet supported for user {user.email}.")
            return Response({"error": f"Link generation for protocol '{user.protocol}' is not yet supported."}, status=status.HTTP_501_NOT_IMPLEMENTED)

class AlertRuleViewSet(viewsets.ModelViewSet):
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer

class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer

class UserTrafficStatsView(APIView):
    # permission_classes = [IsAuthenticated]
    def get(self, request, user_pk, format=None):
        logger.info(f"Received request for traffic stats for user_pk: {user_pk}")
        xray_user = get_object_or_404(XrayUser, pk=user_pk)
        server_instance = xray_user.server
        if not server_instance:
            logger.error(f"Server instance not found for user {xray_user.email} (pk: {user_pk}).")
            return Response({"error": "Server configuration not found for this user."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        client_inbound_tag = getattr(server_instance, 'api_inbound_tag', None)
        client = XrayClient(server_address=server_instance.address, server_port=server_instance.port, api_token=server_instance.api_token, inbound_tag=client_inbound_tag)
        if not client.is_connected():
            logger.error(f"Failed to connect to Xray server {server_instance.name} for traffic stats (user: {xray_user.email}).")
            return Response({"error": "Failed to connect to Xray server."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            traffic_data = client.get_user_traffic(email=xray_user.email)
            if traffic_data is not None:
                logger.info(f"Successfully retrieved traffic for {xray_user.email}: {traffic_data}")
                return Response(traffic_data, status=status.HTTP_200_OK)
            else:
                logger.warning(f"No traffic data returned from Xray server for user {xray_user.email}.")
                return Response({"error": "No traffic data available or error fetching from Xray."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Exception while fetching traffic for user {xray_user.email}: {e}", exc_info=True)
            return Response({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            if client: client.close()

class UserOnlineStatusView(APIView):
    # permission_classes = [IsAuthenticated]
    def get(self, request, user_pk, format=None):
        logger.info(f"Received request for online status for user_pk: {user_pk}")
        xray_user = get_object_or_404(XrayUser, pk=user_pk)
        server_instance = xray_user.server
        if not server_instance:
            logger.error(f"Server instance not found for user {xray_user.email} (pk: {user_pk}).")
            return Response({"error": "Server configuration not found for this user."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        client_inbound_tag = getattr(server_instance, 'api_inbound_tag', None)
        client = XrayClient(server_address=server_instance.address, server_port=server_instance.port, api_token=server_instance.api_token, inbound_tag=client_inbound_tag)
        if not client.is_connected():
            logger.error(f"Failed to connect to Xray server {server_instance.name} for online status (user: {xray_user.email}).")
            return Response({"error": "Failed to connect to Xray server."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            online_ips = client.get_user_online_status(email=xray_user.email)
            logger.info(f"Successfully retrieved online status for {xray_user.email}: {online_ips}")
            return Response({"online_ips": online_ips, "is_online": bool(online_ips)}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Exception while fetching online status for user {xray_user.email}: {e}", exc_info=True)
            return Response({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            if client: client.close()

if __name__ == '__main__':
    # --- Configuration for Testing ---
    # IMPORTANT: Replace these values with your actual Xray server details for testing.
    XRAY_SERVER_ADDRESS = "127.0.0.1"  # Example: "your_xray_server_ip_or_domain"
    XRAY_SERVER_API_PORT = 10085       # Default Xray API port, change if different
    XRAY_API_TOKEN = None              # Example: "your_secret_api_token" or None if not used
    TARGET_INBOUND_TAG = "your_inbound_tag" # Example: "vless-inbound" or the tag of your test inbound

    TEST_USER_EMAIL = "test@example.com"
    TEST_USER_UUID = "your-uuid-here" # Generate a valid UUID for testing add_user
    TEST_USER_PROTOCOL = "vless" # Protocol for add_user (currently only informational)

    # --- Setup Logging ---
    # You can set the logging level to DEBUG for more verbose output from grpc.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    # For very detailed gRPC logs (optional, can be noisy):
    # import os
    # os.environ['GRPC_TRACE'] = 'all'
    # os.environ['GRPC_VERBOSITY'] = 'DEBUG'

    logger.info("--- Starting XrayClient Test Script ---")

    # --- Initialize Client ---
    # Pass setup_logging=False if basicConfig is already handled by the application
    client = XrayClient(
        server_address=XRAY_SERVER_ADDRESS,
        server_port=XRAY_SERVER_API_PORT,
        api_token=XRAY_API_TOKEN,
        inbound_tag=TARGET_INBOUND_TAG # Default inbound tag for operations
    )

    if not PROTOS_LOADED:
        logger.critical("Proto files failed to load. Exiting test script.")
        exit(1) # Changed from pass to exit for a script

    if not client.is_connected():
        logger.error(f"Failed to connect to Xray server at {XRAY_SERVER_ADDRESS}:{XRAY_SERVER_API_PORT}. Please check server status and client configuration.")
        logger.info("--- XrayClient Test Script Finished (with connection error) ---")
        exit(1) # Changed from pass to exit for a script

    logger.info(f"Successfully connected to Xray server. Default inbound tag: {client.inbound_tag}")

    try:
        # --- Test get_users ---
        logger.info(f"\n--- Testing get_users from inbound: {TARGET_INBOUND_TAG} ---")
        users = client.get_users() # Uses default inbound_tag from client
        if users:
            logger.info(f"Found {len(users)} users:")
            for u in users:
                logger.info(f"  - Email: {u.get('email')}, Level: {u.get('level')}")
        else:
            logger.info("No users found or an error occurred.")

        # --- Test add_user (simplified) ---
        # Note: This simplified version might not work if Xray server requires full account details.
        logger.info(f"\n--- Testing add_user (simplified): {TEST_USER_EMAIL} ---")
        add_success = client.add_user(
            email=TEST_USER_EMAIL,
            user_uuid=TEST_USER_UUID,
            protocol=TEST_USER_PROTOCOL
        )
        if add_success:
            logger.info(f"add_user request for {TEST_USER_EMAIL} sent successfully.")
            # Verify by getting users again
            users_after_add = client.get_users()
            logger.info(f"Users after add attempt: {users_after_add}")
            found_new_user = any(u.get('email') == TEST_USER_EMAIL for u in users_after_add)
            logger.info(f"Was user {TEST_USER_EMAIL} found in list after add? {found_new_user}")
        else:
            logger.error(f"Failed to send add_user request for {TEST_USER_EMAIL}.")

        # --- Test get_user_traffic ---
        # This requires the user (TEST_USER_EMAIL) to exist and have traffic stats enabled/available.
        logger.info(f"\n--- Testing get_user_traffic for: {TEST_USER_EMAIL} ---")
        traffic = client.get_user_traffic(TEST_USER_EMAIL)
        if traffic:
            logger.info(f"Traffic for {TEST_USER_EMAIL}: Uplink={traffic['uplink']} bytes, Downlink={traffic['downlink']} bytes")
        else:
            logger.warning(f"Could not retrieve traffic for {TEST_USER_EMAIL} or user has no traffic data.")

        # --- Test get_user_online_status ---
        # This requires the user to be online or have recent activity, and stats enabled.
        logger.info(f"\n--- Testing get_user_online_status for: {TEST_USER_EMAIL} ---")
        online_status = client.get_user_online_status(TEST_USER_EMAIL)
        if online_status:
            logger.info(f"Online status for {TEST_USER_EMAIL}:")
            for status in online_status:
                logger.info(f"  - IP: {status.get('ip')}, Last Activity: {status.get('last_activity_timestamp')}")
        else:
            logger.warning(f"No online status for {TEST_USER_EMAIL} or user is offline/stats unavailable.")

        # --- Test remove_user ---
        # Be careful with this on a production server.
        logger.info(f"\n--- Testing remove_user: {TEST_USER_EMAIL} ---")
        remove_success = client.remove_user(TEST_USER_EMAIL)
        if remove_success:
            logger.info(f"remove_user request for {TEST_USER_EMAIL} sent successfully.")
            # Verify by getting users again
            users_after_remove = client.get_users()
            logger.info(f"Users after remove attempt: {users_after_remove}")
            found_removed_user = any(u.get('email') == TEST_USER_EMAIL for u in users_after_remove)
            logger.info(f"Was user {TEST_USER_EMAIL} still found in list after remove? {'Yes, removal might have failed or not processed yet.' if found_removed_user else 'No, user seems removed.'}")
        else:
            logger.error(f"Failed to send remove_user request for {TEST_USER_EMAIL}.")

    except Exception as e:
        logger.error(f"An unexpected error occurred during the test script: {e}", exc_info=True)
    finally:
        # --- Close Connection ---
        if client:
            client.close()
        logger.info("\n--- XrayClient Test Script Finished ---")
    # Removed pass, as exit(1) is used for script termination on errors
