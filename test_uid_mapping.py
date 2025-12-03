#!/usr/bin/env python3
from fritzconnection.lib.fritzhosts import FritzHosts

fc = FritzHosts(address='192.168.178.1', user='dominikhahn', password='19_Katharina_88')
mesh = fc.get_mesh_topology()

uid_to_unique_name = {}

for node_info in mesh.get('nodes', []):
    node_uid = node_info.get('uid', '')
    mesh_mac = node_info.get('device_mac_address', '').upper()
    device_name = node_info.get('device_name', '')
    
    if not node_uid:
        print(f"SKIP: no UID for {device_name}")
        continue
    
    vendor_id = (node_info.get('device_vendor_class_id') or '').upper()
    caps = node_info.get('device_capabilities') or []
    
    is_router = device_name and device_name.lower() in ('fritz.box',)
    is_powerline = 'POWERLINE' in vendor_id
    is_repeater = ('REPEATER' in vendor_id or 'WLAN_ACCESS_POINT' in caps) and not is_powerline and not is_router
    
    print(f"UID: {node_uid:10} Name: {device_name:30} is_router={is_router}, is_repeater={is_repeater}, is_powerline={is_powerline}")
    
    if is_router or is_repeater or is_powerline:
        if is_router:
            unique_name = 'fritz.box'
        elif is_powerline:
            mac_suffix = mesh_mac.replace(':', '')[-4:]
            unique_name = f"Powerline-{mac_suffix}"
        elif is_repeater:
            mac_suffix = mesh_mac.replace(':', '')[-4:]
            unique_name = f"Repeater-{mac_suffix}"
        
        uid_to_unique_name[node_uid] = unique_name
        print(f"  -> MAPPED to {unique_name}")

print(f"\nTotal mappings: {len(uid_to_unique_name)}")
for uid, name in sorted(uid_to_unique_name.items()):
    print(f"  {uid:10} -> {name}")
