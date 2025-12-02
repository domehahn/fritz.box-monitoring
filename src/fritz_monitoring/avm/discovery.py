from .models import Node, Device
from .connection import FritzClient
import json
import os

class MeshDiscovery:
    def __init__(self, client: FritzClient) -> None:
        self.client = client
        self._load_optional_overrides()

    def _load_optional_overrides(self):
        """Load optional manual overrides (only needed for edge cases)."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            'config',
            'network_topology.json'
        )
        
        # Optional overrides - system works fully without them!
        self.static_ip_to_repeater = {}  # Fallback: wenn WLAN-AP-Zuordnung fehlt
        self.manual_hierarchy = {}  # Fallback: wenn API Hierarchie falsch erkennt
        self.model_name_mapping = {}  # Optional: schönere Namen
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    self.static_ip_to_repeater = config.get('static_ip_to_repeater', {})
                    self.manual_hierarchy = config.get('manual_hierarchy', {})
                    self.model_name_mapping = config.get('model_name_mapping', {})
                    print(f"Loaded optional overrides: {len(self.static_ip_to_repeater)} IPs, "
                          f"{len(self.manual_hierarchy)} hierarchy entries")
            else:
                print("No manual overrides - using 100% automatic discovery")
        except Exception as e:
            print(f"Config load failed (continuing with auto-detection): {e}")

    def discover(self) -> tuple[list[Node], list[Device]]:
        """Return all mesh nodes and all devices with node assignments."""
        nodes = []
        devices = []
        
        if not self.client:
            return nodes, devices
        
        try:
            # Get WLAN associations to map WiFi devices to their access points
            wlan_devices = self.client.get_wlan_devices()
            device_mac_to_ap_mac = {}
            for wlan_dev in wlan_devices:
                device_mac_to_ap_mac[wlan_dev['device_mac'].upper()] = wlan_dev['ap_mac'].upper()
            
            print(f"Built WLAN association map with {len(device_mac_to_ap_mac)} devices")
            
            # Use loaded configuration
            static_ip_to_repeater = self.static_ip_to_repeater
            model_name_mapping = self.model_name_mapping
            manual_hierarchy = self.manual_hierarchy
            
            print(f"Loaded {len(static_ip_to_repeater)} static IP-to-repeater mappings")
            
            # Get mesh topology for device-to-node mapping
            print("About to call get_mesh_info()...")
            mesh_topology = self.client.get_mesh_info()
            print(f"Mesh topology: {mesh_topology is not None}, nodes: {len(mesh_topology.get('nodes', [])) if mesh_topology else 0}")
            device_ip_to_node = {}
            node_uid_to_name = {}
            mac_to_mesh_name = {}  # Map device MAC to unique mesh name
            ap_mac_to_mesh_name = {}  # Map WLAN AP MAC to mesh name
            type_by_mac: dict[str, dict] = {}
            
            if mesh_topology:
                # First pass: map node_uid -> device_name and mac -> device_name for all mesh nodes
                for node_info in mesh_topology.get('nodes', []):
                    node_uid = node_info.get('uid', '')
                    device_name = node_info.get('device_name', '')
                    mac_addr = node_info.get('device_mac_address', '')
                    
                    if node_uid and device_name:
                        node_uid_to_name[node_uid] = device_name
                    
                    if mac_addr and device_name:
                        mac_to_mesh_name[mac_addr.upper()] = device_name
                    
                    # Also map WLAN interface MACs to this device name (for WiFi association)
                    for interface in node_info.get('node_interfaces', []):
                        if interface.get('type') == 'WLAN':
                            wlan_mac = interface.get('mac_address', '').upper()
                            if wlan_mac and device_name:
                                ap_mac_to_mesh_name[wlan_mac] = device_name

                    vendor_id = (node_info.get('device_vendor_class_id') or '').upper()
                    caps = node_info.get('device_capabilities') or []
                    is_repeater = 'REPEATER' in vendor_id or 'WLAN_ACCESS_POINT' in caps
                    is_powerline = 'POWERLINE' in vendor_id
                    is_router = device_name.lower() in ('fritz.box',)
                    if mac_addr:
                        type_by_mac[mac_addr.upper()] = {
                            'is_router': is_router,
                            'is_repeater': is_repeater,
                            'is_powerline': is_powerline,
                        }
                
                print(f"Mapped {len(ap_mac_to_mesh_name)} AP MACs to mesh nodes")
                
                # Build mesh node hierarchy from node_links
                # Maps node MAC -> parent node name (upstream connection)
                node_mac_to_parent_name = {}
                node_uid_to_mac = {}  # Map UID to MAC
                for node_info in mesh_topology.get('nodes', []):
                    node_uid = node_info.get('uid', '')
                    mac_addr = node_info.get('device_mac_address', '').upper()
                    if node_uid and mac_addr:
                        node_uid_to_mac[node_uid] = mac_addr
                
                for node_info in mesh_topology.get('nodes', []):
                    this_node_uid = node_info.get('uid', '')
                    this_node_mac = node_info.get('device_mac_address', '').upper()
                    
                    # Look for upstream connection in node_interfaces
                    for interface in node_info.get('node_interfaces', []):
                        for link in interface.get('node_links', []):
                            # Link connects node_1_uid <-> node_2_uid
                            node_1_uid = link.get('node_1_uid', '')
                            node_2_uid = link.get('node_2_uid', '')
                            
                            # Find which one is the upstream node (parent)
                            parent_uid = None
                            if node_1_uid == this_node_uid and node_2_uid in node_uid_to_name:
                                parent_uid = node_2_uid
                            elif node_2_uid == this_node_uid and node_1_uid in node_uid_to_name:
                                parent_uid = node_1_uid
                            
                            if parent_uid:
                                # Store parent UID (we'll resolve to unique name later)
                                if this_node_mac:
                                    node_mac_to_parent_name[this_node_mac] = parent_uid
                                break
                
                print(f"Node hierarchy extracted: {len(node_mac_to_parent_name)} nodes with parents")
                
                # Extract IP addresses from mesh topology for infrastructure nodes
                mesh_mac_to_ip = {}
                for node_info in mesh_topology.get('nodes', []):
                    mac_addr = node_info.get('device_mac_address', '').upper()
                    if mac_addr:
                        # Get device IP address from ip_addresses list
                        for ip_info in node_info.get('ip_addresses', []):
                            if ip_info.get('version') == 'V4':
                                ip_addr = ip_info.get('value', '').split('/')[0]
                                if ip_addr and not ip_addr.startswith('169.'):  # Skip link-local
                                    mesh_mac_to_ip[mac_addr] = ip_addr
                                    break
                
                print(f"Extracted {len(mesh_mac_to_ip)} IPs from mesh topology")
                
                # Second pass: for each device, find which node it connects to via node_links
                # Store UID instead of name so we can map to unique_name later
                device_ip_to_node_uid = {}
                for node_info in mesh_topology.get('nodes', []):
                    # Get device IP address from ip_addresses list
                    device_ip = ''
                    for ip_info in node_info.get('ip_addresses', []):
                        if ip_info.get('version') == 'V4' and 'DHCP' in ip_info.get('attributes', []):
                            device_ip = ip_info.get('value', '').split('/')[0]
                            break
                    
                    if not device_ip:
                        continue
                    
                    # Look for upstream connection in node_interfaces
                    for interface in node_info.get('node_interfaces', []):
                        for link in interface.get('node_links', []):
                            # Link connects node_1_uid <-> node_2_uid
                            node_1_uid = link.get('node_1_uid', '')
                            node_2_uid = link.get('node_2_uid', '')
                            
                            # Find which one is the upstream node (not this device)
                            this_node_uid = node_info.get('uid', '')
                            if node_1_uid == this_node_uid and node_2_uid:
                                device_ip_to_node_uid[device_ip] = node_2_uid
                                break
                            elif node_2_uid == this_node_uid and node_1_uid:
                                device_ip_to_node_uid[device_ip] = node_1_uid
                                break
                
                print(f"Device IP to node UID mappings: {len(device_ip_to_node_uid)}")
            
            # Get all hosts
            hosts_info = self.client.get_all_hosts()
            
            # First pass: build complete mapping of ALL mesh names to unique names
            # We need to process both mesh topology nodes AND hosts
            mesh_name_to_unique_name = {}
            mesh_name_to_mac = {}  # Track which MAC each mesh name belongs to
            
            # Map all nodes from mesh topology first
            if mesh_topology:
                for node_info in mesh_topology.get('nodes', []):
                    device_name = node_info.get('device_name', '')
                    mac_addr = node_info.get('device_mac_address', '')
                    if device_name and mac_addr:
                        mesh_name_to_mac[device_name] = mac_addr.upper()
            
            # Now process hosts to create unique names
            for host in hosts_info:
                name = host.get('name', 'Unknown')
                mac = host.get('mac', '')
                
                # Determine if this is infrastructure
                upper_name = name.upper()
                mac_key = (mac or '').upper()
                mesh_type = type_by_mac.get(mac_key, {})
                is_repeater = bool(mesh_type.get('is_repeater')) or ('REPEATER' in upper_name)
                is_powerline = bool(mesh_type.get('is_powerline')) or ('POWERLINE' in upper_name) or ('AVM1220' in upper_name) or ('AVM1260' in upper_name)
                is_router = bool(mesh_type.get('is_router')) or (upper_name.startswith('FRITZ.BOX') or upper_name == 'FRITZ.BOX')

                if is_router or is_repeater or is_powerline:
                    # Get mesh name and create unique name
                    mac_upper = (mac or '').upper()
                    mesh_name = mac_to_mesh_name.get(mac_upper)
                    
                    if not mesh_name:
                        # Fallback: create a unique name using last 4 chars of MAC
                        if is_repeater:
                            mac_suffix = mac.replace(':', '')[-4:] if mac else 'Unknown'
                            unique_name = f"Repeater-{mac_suffix}"
                        elif is_powerline:
                            mac_suffix = mac.replace(':', '')[-4:] if mac else 'Unknown'
                            unique_name = f"Powerline-{mac_suffix}"
                        else:
                            unique_name = name
                    else:
                        unique_name = mesh_name
                    
                    # Store mapping from mesh name to unique name
                    if mesh_name:
                        mesh_name_to_unique_name[mesh_name] = unique_name
                    mesh_name_to_unique_name[name] = unique_name  # Also map host name
            
            # Build UID to unique_name mapping using MAC address
            uid_to_unique_name = {}
            mac_to_unique_name = {}  # Helper mapping
            
            # First build MAC -> unique_name from mesh_name mappings (for infrastructure)
            for mesh_name, mac_addr in mesh_name_to_mac.items():
                unique_name = mesh_name_to_unique_name.get(mesh_name)
                if unique_name:
                    mac_to_unique_name[mac_addr] = unique_name
            
            # Also add all hosts to mac_to_unique_name
            for host in hosts_info:
                mac = host.get('mac', '').upper()
                name = host.get('name', '')
                unique_name = mesh_name_to_unique_name.get(name)
                if mac and unique_name and mac not in mac_to_unique_name:
                    mac_to_unique_name[mac] = unique_name
            
            # Now map UID -> unique_name via MAC for ALL nodes in mesh topology
            if mesh_topology:
                for node_info in mesh_topology.get('nodes', []):
                    node_uid = node_info.get('uid', '')
                    mac_addr = node_info.get('device_mac_address', '').upper()
                    device_name = node_info.get('device_name', '')
                    
                    if node_uid:
                        # Try MAC first
                        if mac_addr and mac_addr in mac_to_unique_name:
                            uid_to_unique_name[node_uid] = mac_to_unique_name[mac_addr]
                        # Fall back to device_name mapping
                        elif device_name and device_name in mesh_name_to_unique_name:
                            uid_to_unique_name[node_uid] = mesh_name_to_unique_name[device_name]
                        # Last resort: create unique name from node type and MAC
                        elif mac_addr:
                            vendor_id = (node_info.get('device_vendor_class_id') or '').upper()
                            caps = node_info.get('device_capabilities') or []
                            is_repeater = 'REPEATER' in vendor_id or 'WLAN_ACCESS_POINT' in caps
                            is_powerline = 'POWERLINE' in vendor_id
                            is_router = device_name and device_name.lower() in ('fritz.box',)
                            
                            if is_router:
                                uid_to_unique_name[node_uid] = 'fritz.box'
                            elif is_repeater:
                                mac_suffix = mac_addr.replace(':', '')[-4:]
                                uid_to_unique_name[node_uid] = f"Repeater-{mac_suffix}"
                            elif is_powerline:
                                mac_suffix = mac_addr.replace(':', '')[-4:]
                                uid_to_unique_name[node_uid] = f"Powerline-{mac_suffix}"
            
            print(f"UID to unique_name mappings: {len(uid_to_unique_name)}")
            
            # Debug: show sample IP mappings
            sample_ips = list(device_ip_to_node_uid.items())[:10]
            for ip, uid in sample_ips:
                unique = uid_to_unique_name.get(uid, f"UID:{uid[:10]}")
                print(f"  {ip:20} -> {unique}")
            
            # Map any remaining mesh names that weren't in the host list (offline repeaters, etc.)
            # Only create Node objects for actual infrastructure (repeater/powerline/router)
            # Use dict to prevent duplicates by MAC
            nodes_by_mac = {}  # mac -> Node
            
            for mesh_name, mac_addr in mesh_name_to_mac.items():
                if mesh_name not in mesh_name_to_unique_name:
                    # This node is in mesh topology but not in host list
                    # Check if it's actually infrastructure
                    mesh_type = type_by_mac.get(mac_addr, {})
                    is_repeater = mesh_type.get('is_repeater', False)
                    is_powerline = mesh_type.get('is_powerline', False)
                    is_router = mesh_type.get('is_router', False)
                    
                    # Only create nodes for infrastructure, skip regular devices
                    if not (is_repeater or is_powerline or is_router):
                        # Regular device in mesh, not infrastructure - just map the name
                        mac_suffix = mac_addr.replace(':', '')[-4:] if mac_addr else 'Unknown'
                        mesh_name_to_unique_name[mesh_name] = f"Device-{mac_suffix}"
                        continue
                    
                    mac_suffix = mac_addr.replace(':', '')[-4:] if mac_addr else 'Unknown'
                    
                    # Create unique name based on type
                    if is_repeater:
                        unique_name = f"Repeater-{mac_suffix}"
                    elif is_powerline:
                        unique_name = f"Powerline-{mac_suffix}"
                    elif is_router:
                        unique_name = "fritz.box"
                    else:
                        unique_name = f"Node-{mac_suffix}"
                    
                    mesh_name_to_unique_name[mesh_name] = unique_name
                    
                    # Create Node object for mesh-only infrastructure nodes
                    # Parent resolution will happen after all unique names are known
                    # Get model name from mapping or use mesh_name as fallback
                    model_display_name = model_name_mapping.get(mesh_name, mesh_name or unique_name)
                    
                    # Get IP from mesh topology if available
                    node_ip = mesh_mac_to_ip.get(mac_addr, "")
                    
                    node = Node(
                        name=unique_name,
                        mac=mac_addr,
                        ip=node_ip,  # Use mesh topology IP
                        is_router=is_router,
                        is_repeater=is_repeater,
                        is_powerline=is_powerline,
                        extra={'active': True, 'mesh_only': True, 'model': model_display_name, 'parent_uid': node_mac_to_parent_name.get(mac_addr.upper())},
                        parent_node=None  # Will be resolved later
                    )
                    nodes_by_mac[mac_addr.upper()] = node            # Second pass: create nodes and devices with correct mappings
            for host in hosts_info:
                name = host.get('name', 'Unknown')
                mac = host.get('mac', '')
                ip = host.get('ip', '')
                active = host.get('status', False)
                interface_type = host.get('interface_type', '')
                
                # Only treat mesh infrastructure as nodes (router, repeater, powerline)
                upper_name = name.upper()
                # Prefer mesh-derived type by MAC if available
                mac_key = (mac or '').upper()
                mesh_type = type_by_mac.get(mac_key, {})
                is_repeater = bool(mesh_type.get('is_repeater')) or ('REPEATER' in upper_name)
                is_powerline = bool(mesh_type.get('is_powerline')) or ('POWERLINE' in upper_name) or ('AVM1220' in upper_name) or ('AVM1260' in upper_name)
                is_router = bool(mesh_type.get('is_router')) or (upper_name.startswith('FRITZ.BOX') or upper_name == 'FRITZ.BOX')

                if is_router or is_repeater or is_powerline:
                    # Infrastructure node - create unique standardized name
                    mac_upper = (mac or '').upper()
                    mesh_name = mac_to_mesh_name.get(mac_upper)
                    
                    # Always create standardized unique names for infrastructure
                    if is_router:
                        unique_name = "fritz.box"
                    elif is_repeater:
                        mac_suffix = mac.replace(':', '')[-4:] if mac else 'Unknown'
                        unique_name = f"Repeater-{mac_suffix}"
                    elif is_powerline:
                        mac_suffix = mac.replace(':', '')[-4:] if mac else 'Unknown'
                        unique_name = f"Powerline-{mac_suffix}"
                    else:
                        unique_name = name
                    
                    # Store mappings so mesh_name and host_name both resolve to unique_name
                    if mesh_name:
                        mesh_name_to_unique_name[mesh_name] = unique_name
                    mesh_name_to_unique_name[name] = unique_name
                    
                    # Get model name from mapping or use original name as fallback
                    model_display_name = model_name_mapping.get(mesh_name or name, name)
                    
                    # Update existing node or create new one
                    parent_uid = node_mac_to_parent_name.get(mac_upper)
                    
                    if mac_upper in nodes_by_mac:
                        # Update existing mesh-only node with host data
                        node = nodes_by_mac[mac_upper]
                        node.ip = ip
                        node.extra['active'] = active
                        node.extra['model'] = model_display_name
                        node.extra['parent_uid'] = parent_uid
                    else:
                        # Create new node from host
                        node = Node(
                            name=unique_name,
                            mac=mac,
                            ip=ip,
                            is_router=is_router,
                            is_repeater=is_repeater,
                            is_powerline=is_powerline,
                            extra={'active': active, 'model': model_display_name, 'parent_uid': parent_uid},
                            parent_node=None  # Will be resolved later
                        )
                        nodes_by_mac[mac_upper] = node
                else:
                    # All other devices - use WLAN associations, then static IP mapping, then mesh IP mapping, fallback to fritz.box
                    connected_node_mesh_name = None
                    connected_node_uid = None
                    mapping_source = "none"
                    
                    # 1. BEST: WLAN association (most reliable for WiFi devices)
                    mac_upper = (mac or '').upper()
                    if mac_upper in device_mac_to_ap_mac:
                        ap_mac = device_mac_to_ap_mac[mac_upper]
                        # Find which node has this AP MAC (using WLAN interface MACs)
                        connected_node_mesh_name = ap_mac_to_mesh_name.get(ap_mac, '')
                        if connected_node_mesh_name:
                            mapping_source = "wlan"
                    
                    # 2. GOOD: Mesh topology IP mapping (for wired devices)
                    if not connected_node_mesh_name and ip in device_ip_to_node_uid:
                        connected_node_uid = device_ip_to_node_uid[ip]
                        if connected_node_uid:
                            mapping_source = "mesh_ip"
                    
                    # 3. FALLBACK: Static IP mapping (only if above fails)
                    # This is useful for devices where API doesn't report association
                    if not connected_node_mesh_name and ip and ip in static_ip_to_repeater:
                        connected_node_mesh_name = static_ip_to_repeater[ip]
                        mapping_source = "static_ip_override"
                    
                    # 4. DEFAULT: Connected to main router
                    if not connected_node_mesh_name and not connected_node_uid:
                        connected_node_mesh_name = "fritz.box"
                        mapping_source = "default_router"
                    
                    # Map mesh name or UID to unique name
                    if mapping_source == "static_ip":
                        connected_node = connected_node_mesh_name  # Already a unique name
                    elif mapping_source == "mesh_ip":
                        connected_node = uid_to_unique_name.get(connected_node_uid, 'fritz.box')
                    else:
                        connected_node = mesh_name_to_unique_name.get(connected_node_mesh_name, connected_node_mesh_name)
                    
                    device = Device(
                        name=name,
                        mac=mac,
                        ip=ip,
                        online=active,
                        interface_type=interface_type,
                        connected_node=connected_node,
                        rx_bytes_total=None,
                        tx_bytes_total=None,
                        extra={'interface': interface_type, 'mapping': mapping_source}
                    )
                    devices.append(device)
            
            # Final step: resolve all parent UIDs to unique names
            nodes = []
            for node in nodes_by_mac.values():
                # First check manual hierarchy override
                mac_upper = node.mac.upper()
                if mac_upper in manual_hierarchy:
                    node.parent_node = manual_hierarchy[mac_upper]
                else:
                    # Fall back to API-detected hierarchy
                    parent_uid = node.extra.get('parent_uid')
                    if parent_uid:
                        # Resolve parent UID to unique name
                        parent_unique_name = uid_to_unique_name.get(parent_uid)
                        if parent_unique_name:
                            # Further resolve if parent_unique_name is a mesh name
                            node.parent_node = mesh_name_to_unique_name.get(parent_unique_name, parent_unique_name)
                        else:
                            node.parent_node = None
                    else:
                        node.parent_node = None
                nodes.append(node)

                    
        except Exception as e:
            print(f"Error during discovery: {e}")
            import traceback
            traceback.print_exc()
        
        return nodes, devices
