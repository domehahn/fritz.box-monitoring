#!/usr/bin/env python3
from fritzconnection.lib.fritzhosts import FritzHosts

fc = FritzHosts(address='192.168.178.1', user='dominikhahn', password='19_Katharina_88')
mesh = fc.get_mesh_topology()
hosts = fc.get_hosts_info()

# Simulate the logic
mac_to_unique_name = {}

print("STEP 1: Add host MACs (lines 285-290)")
print("=" * 80)
# First: Add host MACs (like line 285-290)
for host in hosts:
    mac = host.get('mac', '').upper()
    name = host.get('name', '')
    if 'repeater' in name.lower() or 'garage' in name.lower() or 'og' in name.lower() or 'eg' in name.lower():
        if mac:
            # Using host MAC (wrong!)
            mac_suffix = mac.replace(':', '')[-4:]
            unique_name = f'Repeater-{mac_suffix}'
            mac_to_unique_name[mac] = unique_name
            print(f'HOST: {mac:20} -> {unique_name:20} (name: {name})')

print()
print("STEP 2: Override with mesh MACs (lines 293-328)")
print("=" * 80)

# Second: Override with mesh MACs (like line 293-328)
for node in mesh.get('nodes', []):
    vendor = (node.get('device_vendor_class_id') or '').upper()
    caps = node.get('device_capabilities') or []
    is_repeater = 'REPEATER' in vendor or 'WLAN_ACCESS_POINT' in caps
    
    if is_repeater:
        mesh_mac = node.get('device_mac_address', '').upper()
        device_name = node.get('device_name', '')
        mac_suffix = mesh_mac.replace(':', '')[-4:]
        unique_name = f'Repeater-{mac_suffix}'
        mac_to_unique_name[mesh_mac] = unique_name  # This adds MESH MAC (different from host!)
        print(f'MESH: {mesh_mac:20} -> {unique_name:20} ({device_name})')

print()
print("Final mac_to_unique_name (should have BOTH host and mesh MACs!):")
print("=" * 80)
for mac, name in sorted(mac_to_unique_name.items()):
    print(f'  {mac:20} -> {name}')
