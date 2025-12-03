#!/usr/bin/env python3
"""
Fritz!Box Device Management Web Interface
Allows viewing and deleting offline/unknown devices
"""
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from fritzconnection import FritzConnection
from fritzconnection.lib.fritzhosts import FritzHosts
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Fritz!Box connection config from environment
FRITZ_HOST = os.getenv('FRITZ_HOST', 'fritz.box')
FRITZ_PORT = int(os.getenv('FRITZ_PORT', 49000))
FRITZ_USERNAME = os.getenv('FRITZ_USERNAME', '')
FRITZ_PASSWORD = os.getenv('FRITZ_PASSWORD', '')


def get_fritz_connection():
    """Create Fritz!Box connection"""
    return FritzConnection(
        address=FRITZ_HOST,
        port=FRITZ_PORT,
        user=FRITZ_USERNAME,
        password=FRITZ_PASSWORD
    )


def get_mesh_topology():
    """Get complete mesh topology with nodes and connections"""
    try:
        fc = get_fritz_connection()
        hosts = FritzHosts(fc)

        # Get mesh topology
        mesh_data = hosts.get_mesh_topology()

        if not mesh_data:
            return {'nodes': [], 'links': []}

        # Get all hosts to match IPs and count connected devices
        all_hosts = hosts.get_hosts_info()
        mac_to_ip = {}
        mac_to_interface = {}

        for host in all_hosts:
            mac = host.get('mac', '').upper()
            if mac:
                mac_to_ip[mac] = host.get('ip', '')
                mac_to_interface[mac] = host.get('interface_type', '')

        nodes = []
        links = []
        node_mac_to_uid = {}

        # Build node list with details
        for node_info in mesh_data.get('nodes', []):
            device_name = node_info.get('device_name', 'Unknown')
            device_mac = node_info.get('device_mac_address', '').upper()
            node_uid = node_info.get('uid', '')

            # Store MAC to UID mapping
            node_mac_to_uid[device_mac] = node_uid

            # Get IP from hosts list
            device_ip = mac_to_ip.get(device_mac, '')

            # Determine node type
            vendor_id = (node_info.get('device_vendor_class_id') or '').upper()
            caps = node_info.get('device_capabilities') or []

            is_router = 'fritz.box' in device_name.lower()
            is_repeater = 'REPEATER' in vendor_id or 'WLAN_ACCESS_POINT' in caps
            is_powerline = 'POWERLINE' in vendor_id

            node_type = 'router' if is_router else ('repeater' if is_repeater else ('powerline' if is_powerline else 'unknown'))

            # Count devices connected to this node
            connected_count = 0
            for host in all_hosts:
                # Check if device is connected via this node's interface
                host_interface = host.get('interface_type', '')
                if device_name.lower() in host_interface.lower() or device_mac in host_interface:
                    connected_count += 1

            # Get node interfaces for traffic stats
            rx_bytes = 0
            tx_bytes = 0
            for interface in node_info.get('node_interfaces', []):
                rx_bytes += interface.get('rx_bytes', 0)
                tx_bytes += interface.get('tx_bytes', 0)

            nodes.append({
                'id': node_uid,
                'uid': node_uid,
                'name': device_name,
                'mac': device_mac,
                'ip': device_ip,
                'type': node_type,
                'is_router': is_router,
                'online': True,  # Nodes in mesh topology are online
                'connected_devices': connected_count,
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
            })

        # Build links from node_interfaces
        added_links = set()
        for node_info in mesh_data.get('nodes', []):
            node_uid = node_info.get('uid', '')

            for interface in node_info.get('node_interfaces', []):
                for link in interface.get('node_links', []):
                    node_1_uid = link.get('node_1_uid', '')
                    node_2_uid = link.get('node_2_uid', '')

                    if node_1_uid and node_2_uid:
                        # Create a unique link identifier to avoid duplicates
                        link_key = tuple(sorted([node_1_uid, node_2_uid]))

                        if link_key not in added_links:
                            added_links.add(link_key)
                            links.append({
                                'source': node_1_uid,
                                'target': node_2_uid,
                                'type': interface.get('type', 'unknown')
                            })

        return {'nodes': nodes, 'links': links}

    except Exception as e:
        logger.error(f"Error getting mesh topology: {e}")
        return {'nodes': [], 'links': []}


def get_all_devices():
    """Get all devices from Fritz!Box"""
    try:
        fc = get_fritz_connection()
        hosts = FritzHosts(fc)
        all_hosts = hosts.get_hosts_info()

        devices = []
        for host in all_hosts:
            devices.append({
                'name': host.get('name', 'Unknown'),
                'ip': host.get('ip', ''),
                'mac': host.get('mac', ''),
                'status': host.get('status', False),
                'interface_type': host.get('interface_type', ''),
                'last_active': host.get('last_active', ''),
            })

        return devices
    except Exception as e:
        logger.error(f"Error getting devices: {e}")
        return []


def delete_device_from_fritzbox(mac_address):
    """
    Delete a device from Fritz!Box known hosts
    Note: Fritz!Box API doesn't support direct deletion of host entries.
    This function attempts to remove the device association.
    """
    try:
        fc = get_fritz_connection()

        # Try to delete the host entry
        # Note: This may not work on all Fritz!Box models/firmware versions
        result = fc.call_action(
            'Hosts1',
            'X_AVM-DE_DeleteHostEntry',
            NewMACAddress=mac_address
        )

        logger.info(f"Deleted device with MAC: {mac_address}")
        return True
    except Exception as e:
        logger.warning(f"Could not delete device {mac_address}: {e}")
        logger.info("Note: Some Fritz!Box models don't support programmatic device deletion")
        return False


@app.route('/')
def index():
    """Main page - show all devices"""
    devices = get_all_devices()

    # Separate into online and offline
    online_devices = [d for d in devices if d['status']]
    offline_devices = [d for d in devices if not d['status']]

    return render_template('index.html',
                         online_devices=online_devices,
                         offline_devices=offline_devices,
                         total_devices=len(devices))


@app.route('/topology')
def topology():
    """Network topology card view page"""
    mesh = get_mesh_topology()
    devices = get_all_devices()

    # Count online/offline
    online_count = sum(1 for d in devices if d['status'])

    return render_template('topology.html',
                         topology=mesh,
                         mesh=mesh,
                         devices=devices,
                         total_devices=len(devices),
                         online_count=online_count)


@app.route('/graph')
def graph():
    """Interactive network graph visualization page"""
    mesh = get_mesh_topology()
    devices = get_all_devices()

    # Count online/offline
    online_count = sum(1 for d in devices if d['status'])

    return render_template('graph.html',
                         topology=mesh,
                         mesh=mesh,
                         devices=devices,
                         total_devices=len(devices),
                         online_count=online_count)


@app.route('/api/devices')
def api_devices():
    """API endpoint to get all devices as JSON"""
    devices = get_all_devices()
    return jsonify(devices)


@app.route('/api/topology')
def api_topology():
    """API endpoint to get mesh topology as JSON"""
    topology = get_mesh_topology()
    return jsonify(topology)


@app.route('/api/device/delete/<mac>', methods=['POST'])
def api_delete_device(mac):
    """API endpoint to delete a single device by MAC address"""
    try:
        success = delete_device_from_fritzbox(mac)
        if success:
            return jsonify({'success': True, 'message': f'Device {mac} deleted'})
        else:
            return jsonify({'success': False, 'message': 'Deletion not supported by Fritz!Box or device not found'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/devices/delete-offline', methods=['POST'])
def api_delete_all_offline():
    """API endpoint to delete all offline devices"""
    try:
        devices = get_all_devices()
        offline_devices = [d for d in devices if not d['status']]

        deleted_count = 0
        failed_count = 0

        for device in offline_devices:
            if delete_device_from_fritzbox(device['mac']):
                deleted_count += 1
            else:
                failed_count += 1

        return jsonify({
            'success': True,
            'deleted': deleted_count,
            'failed': failed_count,
            'message': f'Deleted {deleted_count} devices, {failed_count} failed'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/delete/<mac>', methods=['POST'])
def delete_device(mac):
    """Delete a device (web form endpoint)"""
    success = delete_device_from_fritzbox(mac)
    return redirect(url_for('index'))


@app.route('/delete-all-offline', methods=['POST'])
def delete_all_offline():
    """Delete all offline devices (web form endpoint)"""
    devices = get_all_devices()
    offline_devices = [d for d in devices if not d['status']]

    for device in offline_devices:
        delete_device_from_fritzbox(device['mac'])

    return redirect(url_for('index'))


if __name__ == '__main__':
    # Run on all interfaces so it's accessible from outside the container
    app.run(host='0.0.0.0', port=5000, debug=False)
