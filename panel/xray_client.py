import grpc

# Attempt to import generated proto files.
# This structure assumes 'panel' is in PYTHONPATH or the client is used from within 'panel'.
try:
    from .xray_pb.core.app.proxyman.command import command_pb2 as handler_command_pb2
    from .xray_pb.core.app.proxyman.command import command_pb2_grpc as handler_command_pb2_grpc
    from .xray_pb.core.app.stats.command import command_pb2 as stats_command_pb2
    from .xray_pb.core.app.stats.command import command_pb2_grpc as stats_command_pb2_grpc
    from .xray_pb.common.protocol import user_pb2
    from .xray_pb.common.serial import typed_message_pb2
    PROTOS_LOADED = True
except ImportError:
    PROTOS_LOADED = False
    print("ERROR: Could not import generated proto files. Ensure they are generated in panel/xray_pb and PYTHONPATH is correct.")

class XrayClient:
    def __init__(self, server_address: str, server_port: int, api_token: str = None, inbound_tag: str = None):
        self.server_address = server_address
        self.server_port = server_port
        self.api_token = api_token
        self.inbound_tag = inbound_tag

        self.channel = None
        self.handler_stub = None
        self.stats_stub = None

        if PROTOS_LOADED:
            self._connect()
        else:
            print("Client not connecting due to missing proto imports.")

    def _connect(self):
        if not PROTOS_LOADED:
            print("Client not connecting due to missing proto imports.")
            return

        if self.channel is not None:
            # print("DEBUG: gRPC channel already established or connection attempt was made.")
            return

        target = f"{self.server_address}:{self.server_port}"
        print(f"Attempting to connect to gRPC server at {target}")

        try:
            # For now, using insecure channel.
            # TODO: Implement secure channel if api_token is present.
            # One way to handle API token (as metadata):
            # call_credentials = grpc.access_token_call_credentials(self.api_token)
            # channel_credentials = grpc.ssl_channel_credentials() # Assuming TLS for the channel itself
            # composite_credentials = grpc.composite_channel_credentials(channel_credentials, call_credentials)
            # self.channel = grpc.secure_channel(target, composite_credentials)
            # For testing without server / with insecure server:
            self.channel = grpc.insecure_channel(target)

            # Test connection with a timeout
            try:
                grpc.channel_ready_future(self.channel).result(timeout=5) # 5 seconds timeout
                print(f"Successfully connected to gRPC server at {target}.")
            except grpc.FutureTimeoutError:
                print(f"ERROR: Timeout when trying to connect to {target}. Server might be down or incorrect address/port.")
                self.channel = None
                return
            except grpc.RpcError as e:
                print(f"ERROR: RPC error during connection test to {target}: {e.code()} - {e.details()}")
                self.channel = None
                return


            self.handler_stub = handler_command_pb2_grpc.HandlerServiceStub(self.channel)
            self.stats_stub = stats_command_pb2_grpc.StatsServiceStub(self.channel)
            print(f"gRPC stubs created.")
        except Exception as e:
            print(f"ERROR: Failed to connect to gRPC server at {target}: {e}")
            self.channel = None
            self.handler_stub = None
            self.stats_stub = None

    def close(self):
        if self.channel:
            self.channel.close()
            print("gRPC channel closed.")
        self.channel = None
        self.handler_stub = None
        self.stats_stub = None

    def is_connected(self):
        if self.channel is None:
            return False
        try:
            # A more robust check might involve a quick, non-mutating call
            # For now, just check if channel thinks it's ready (might not be fully accurate)
            # grpc.channel_ready_future(self.channel).result(timeout=0.1) # very short timeout
            return True # If channel object exists and no immediate error, assume connected for now
        except:
            return False

    # --- HandlerService Methods (Placeholders) ---
    def add_user(self, email: str, user_uuid: str, protocol: str, level: int = 0, inbound_tag: str = None):
        print(f"Stub: add_user(email={email}, uuid={user_uuid})")
        return None

    def remove_user(self, email: str, inbound_tag: str = None):
        if not self.is_connected():
            print("ERROR: Not connected to Xray server for remove_user.")
            return False

        effective_inbound_tag = inbound_tag or self.inbound_tag
        if not effective_inbound_tag:
            print("ERROR: Inbound tag must be provided either during client initialization or method call for remove_user.")
            return False

        print(f"Attempting to remove user {email} from inbound {effective_inbound_tag}...")
        try:
            remove_op = handler_command_pb2.RemoveUserOperation(email=email)
            operation_msg = typed_message_pb2.TypedMessage(
                type=remove_op.DESCRIPTOR.full_name, # Or the specific type name Xray expects e.g. "xray.app.proxyman.command.RemoveUserOperation"
                value=remove_op.SerializeToString()
            )
            request = handler_command_pb2.AlterInboundRequest(
                tag=effective_inbound_tag,
                operation=operation_msg
            )
            self.handler_stub.AlterInbound(request, timeout=10) # 10 seconds timeout
            print(f"Successfully requested removal of user {email} from inbound {effective_inbound_tag}.")
            return True
        except grpc.RpcError as e:
            print(f"ERROR: gRPC error while removing user {email}: {e.code()} - {e.details()}")
        except Exception as e:
            print(f"ERROR: Unexpected error while removing user {email}: {e}")
        return False

    def get_users(self, inbound_tag: str = None):
        if not self.is_connected():
            print("ERROR: Not connected to Xray server for get_users.")
            return []

        effective_inbound_tag = inbound_tag or self.inbound_tag
        if not effective_inbound_tag:
            print("ERROR: Inbound tag must be provided either during client initialization or method call for get_users.")
            return []

        print(f"Attempting to get users from inbound {effective_inbound_tag}...")
        users_list = []
        try:
            # For GetInboundUsers, email field in request is optional. If empty, returns all users.
            request = handler_command_pb2.GetInboundUserRequest(tag=effective_inbound_tag)
            response = self.handler_stub.GetInboundUsers(request, timeout=10) # 10 seconds timeout

            if response and response.users:
                for user_proto in response.users:
                    # TODO: Deserialize user_proto.account if needed, once VLESS/VMESS protos are available
                    users_list.append({
                        "email": user_proto.email,
                        "level": user_proto.level,
                        # "account_type": user_proto.account.type,
                        # "account_settings": "..." # Deserialized account
                    })
                print(f"Successfully retrieved {len(users_list)} users from inbound {effective_inbound_tag}.")
            else:
                print(f"No users found or empty response from inbound {effective_inbound_tag}.")

        except grpc.RpcError as e:
            print(f"ERROR: gRPC error while getting users: {e.code()} - {e.details()}")
        except Exception as e:
            print(f"ERROR: Unexpected error while getting users: {e}")
        return users_list

    # --- StatsService Methods ---
    def get_user_traffic(self, email: str):
        if not self.is_connected():
            print("ERROR: Not connected to Xray server for get_user_traffic.")
            return None

        print(f"Attempting to get traffic for user {email}...")
        traffic_data = {'uplink': 0, 'downlink': 0}
        try:
            # Construct stat counter names
            # These names depend on Xray's naming convention. Common patterns:
            # user>>><email>>>traffic>>>uplink
            # user>>><email>>>traffic>>>downlink
            # inbound>>><tag>>>traffic>>>uplink (if traffic is per inbound, not per user directly)
            # For this example, we assume user-specific traffic stats are enabled.

            uplink_stat_name = f"user>>>{email}>>>traffic>>>uplink"
            downlink_stat_name = f"user>>>{email}>>>traffic>>>downlink"

            # Get uplink traffic
            req_uplink = stats_command_pb2.GetStatsRequest(name=uplink_stat_name, reset=False)
            res_uplink = self.stats_stub.GetStats(req_uplink, timeout=5)
            if res_uplink and res_uplink.stat:
                traffic_data['uplink'] = res_uplink.stat.value
            else:
                print(f"Warning: No uplink traffic data found for {email} using name {uplink_stat_name}")

            # Get downlink traffic
            req_downlink = stats_command_pb2.GetStatsRequest(name=downlink_stat_name, reset=False)
            res_downlink = self.stats_stub.GetStats(req_downlink, timeout=5)
            if res_downlink and res_downlink.stat:
                traffic_data['downlink'] = res_downlink.stat.value
            else:
                print(f"Warning: No downlink traffic data found for {email} using name {downlink_stat_name}")

            print(f"Successfully retrieved traffic for user {email}: Uplink={traffic_data['uplink']}, Downlink={traffic_data['downlink']}")
            return traffic_data
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"Warning: Traffic stats not found for user {email} (name pattern might be incorrect or stats not enabled). Details: {e.details()}")
            else:
                print(f"ERROR: gRPC error while getting user traffic for {email}: {e.code()} - {e.details()}")
        except Exception as e:
            print(f"ERROR: Unexpected error while getting user traffic for {email}: {e}")
        return None # Return None on error or if stats not found clearly

    def get_user_online_status(self, email: str):
        if not self.is_connected():
            print("ERROR: Not connected to Xray server for get_user_online_status.")
            return [] # Return empty list for no status or error

        print(f"Attempting to get online status for user {email}...")
        online_ips = []
        try:
            # Construct stat counter name for online status.
            # Example: user>>><email>>>online (this is a guess, might need verification from Xray docs)
            # The GetStatsOnlineIpList method in the proto definition expects a GetStatsRequest.
            online_stat_name = f"user>>>{email}>>>online"

            request = stats_command_pb2.GetStatsRequest(name=online_stat_name)
            response = self.stats_stub.GetStatsOnlineIpList(request, timeout=10) # Using the specific RPC from proto

            if response and response.ips:
                # response.ips is a map<string, int64> where string is IP and int64 might be a timestamp or counter
                for ip, timestamp_or_val in response.ips.items():
                    online_ips.append({"ip": ip, "last_activity_timestamp": timestamp_or_val}) # Assuming it's a timestamp
                print(f"Successfully retrieved {len(online_ips)} online IPs for user {email}.")
            else:
                # This might mean the user is not online or the stat name is incorrect / not configured
                print(f"No online IP data found for user {email} using name {online_stat_name}. User might be offline.")

        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"Warning: Online status not found for user {email} (name pattern might be incorrect or feature not enabled). Details: {e.details()}")
            elif e.code() == grpc.StatusCode.UNIMPLEMENTED:
                 print(f"ERROR: GetStatsOnlineIpList seems to be unimplemented on the server for user {email} using name {online_stat_name}.")
            else:
                print(f"ERROR: gRPC error while getting user online status for {email}: {e.code()} - {e.details()}")
        except Exception as e:
            print(f"ERROR: Unexpected error while getting user online status for {email}: {e}")
        return online_ips

if __name__ == '__main__':
    print("XrayClient with implemented StatsService methods.")
    # Basic test (requires a running Xray server with API and Stats enabled)
    # import logging
    # logging.basicConfig(level=logging.INFO) # To see print statements from client
    # print("Attempting to create client...")
    # client = XrayClient(server_address='127.0.0.1', server_port=10085, inbound_tag="your_tag") # Replace with actuals
    # if client.is_connected():
    #     print("Client connected.")
    #     # Example: test@example.com - replace with an actual user email on your server
    #     # traffic = client.get_user_traffic("test@example.com")
    #     # if traffic:
    #     #     print(f"Traffic for test@example.com: {traffic}")
    #     # online_status = client.get_user_online_status("test@example.com")
    #     # if online_status:
    #     #     print(f"Online status for test@example.com: {online_status}")
    #     # else:
    #     #     print(f"No online status for test@example.com or user is offline.")
    #     client.close()
    # else:
    #     print("Client failed to connect.")
    pass # End of main
