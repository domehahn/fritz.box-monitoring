#!/bin/bash
# Test script to validate Fritz!Box monitoring metrics

echo "🔍 Fritz!Box Monitoring - Metric Validation"
echo "=========================================="
echo ""

EXPORTER_URL="http://localhost:8000/metrics"

# Function to fetch metrics (with caching to avoid multiple calls)
fetch_metrics() {
    if [ -z "$METRICS_CACHE" ]; then
        METRICS_CACHE=$(curl -s "$EXPORTER_URL")
    fi
    echo "$METRICS_CACHE"
}

# Test 1: Check if exporter is running
echo "1️⃣  Testing Exporter Availability..."
fetch_metrics > /dev/null
if [ -n "$METRICS_CACHE" ]; then
    echo "   ✅ Exporter is reachable at $EXPORTER_URL"
else
    echo "   ❌ ERROR: Cannot reach exporter!"
    exit 1
fi
echo ""

# Test 2: Check WLAN Signal Strength metrics
echo "2️⃣  Testing WLAN Signal Strength Metrics..."
WLAN_SIGNAL_COUNT=$(fetch_metrics | grep -c 'fritz_device_wlan_signal_strength{')
if [ "$WLAN_SIGNAL_COUNT" -gt 0 ]; then
    echo "   ✅ Found $WLAN_SIGNAL_COUNT WLAN signal metrics"
    echo "   Example:"
    fetch_metrics | grep 'fritz_device_wlan_signal_strength{' | head -1 | sed 's/^/   /'
else
    echo "   ⚠️  No WLAN signal metrics found (might be no WiFi devices)"
fi
echo ""

# Test 3: Check WLAN Speed metrics
echo "3️⃣  Testing WLAN Speed Metrics..."
WLAN_SPEED_COUNT=$(fetch_metrics | grep -c 'fritz_device_wlan_speed_mbps{')
if [ "$WLAN_SPEED_COUNT" -gt 0 ]; then
    echo "   ✅ Found $WLAN_SPEED_COUNT WLAN speed metrics"
    echo "   Top 3 speeds:"
    fetch_metrics | grep 'fritz_device_wlan_speed_mbps{' | sed 's/^/   /' | sort -t'}' -k2 -rn | head -3
else
    echo "   ⚠️  No WLAN speed metrics found"
fi
echo ""

# Test 4: Check Node Link Speeds
echo "4️⃣  Testing Mesh Node Link Speeds..."
NODE_LINK_COUNT=$(fetch_metrics | grep -c 'fritz_node_link_rx_kbps{')
if [ "$NODE_LINK_COUNT" -gt 0 ]; then
    echo "   ✅ Found $NODE_LINK_COUNT node link speed metrics"
    echo "   Active nodes (RX > 0):"
    fetch_metrics | grep 'fritz_node_link_rx_kbps{' | grep -v ' 0.0$' | sed 's/^/   /'
else
    echo "   ❌ No node link speed metrics found"
fi
echo ""

# Test 5: Check Repeater Device Counts
echo "5️⃣  Testing Repeater Connected Devices..."
REPEATER_COUNT=$(fetch_metrics | grep -c 'fritz_repeater_connected_devices{')
if [ "$REPEATER_COUNT" -gt 0 ]; then
    echo "   ✅ Found $REPEATER_COUNT repeaters"
    echo "   Device counts:"
    fetch_metrics | grep 'fritz_repeater_connected_devices{' | grep -v ' 0.0$' | sed 's/^/   /'
else
    echo "   ⚠️  No repeater metrics found"
fi
echo ""

# Test 6: Check Powerline Device Counts
echo "6️⃣  Testing Powerline Connected Devices..."
POWERLINE_COUNT=$(fetch_metrics | grep -c 'fritz_powerline_connected_devices{')
if [ "$POWERLINE_COUNT" -gt 0 ]; then
    echo "   ✅ Found $POWERLINE_COUNT powerline adapters"
    echo "   Device counts:"
    fetch_metrics | grep 'fritz_powerline_connected_devices{' | grep -v ' 0.0$' | sed 's/^/   /'
else
    echo "   ⚠️  No powerline metrics found"
fi
echo ""

# Test 7: Check TX bytes metric exists
echo "7️⃣  Testing Device TX Bytes Metric..."
TX_COUNT=$(fetch_metrics | grep -c 'fritz_device_tx_bytes_total{')
if [ "$TX_COUNT" -gt 0 ]; then
    echo "   ✅ Found $TX_COUNT device TX metrics"
    echo "   Note: Values are usually 0 due to Fritz!Box hardware limitation"
else
    echo "   ❌ TX bytes metric not found"
fi
echo ""

# Summary
echo "=========================================="
echo "📊 Summary"
echo "=========================================="
TOTAL_METRICS=$(fetch_metrics | grep -v '^#' | grep -c 'fritz_')
echo "Total Fritz metrics: $TOTAL_METRICS"

ACTIVE_NODES=$(fetch_metrics | grep 'fritz_node_link_rx_kbps{' | grep -v ' 0.0$' | wc -l | tr -d ' ')
echo "Active mesh nodes: $ACTIVE_NODES"

TOTAL_DEVICES=$(fetch_metrics | grep 'fritz_device_up{' | grep -c ' 1.0$')
echo "Online devices: $TOTAL_DEVICES"

echo ""
echo "✅ All tests completed!"
echo ""
echo "💡 Tip: Use these Grafana queries:"
echo "   - WLAN Signal: fritz_device_wlan_signal_strength"
echo "   - WLAN Speed: fritz_device_wlan_speed_mbps"
echo "   - Repeater Traffic: fritz_node_link_rx_kbps{type=\"repeater\"} / 1000"
echo "   - Powerline Traffic: fritz_node_link_rx_kbps{type=\"powerline\"} / 1000"
