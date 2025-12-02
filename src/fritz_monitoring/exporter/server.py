from aiohttp import web
import json
from .prometheus_exporter import FritzPrometheusExporter
from ..avm.discovery import MeshDiscovery
from ..avm.connection import FritzClient
from ..avm.logs import FritzLogCollector
from ..config import Settings

class MetricsServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exporter = FritzPrometheusExporter()
        self.fritz_client = FritzClient(settings)
        self.discovery = MeshDiscovery(self.fritz_client)
        self.log_collector = FritzLogCollector(self.fritz_client)
        self.app = web.Application()
        self.app.add_routes([
            web.get("/metrics", self.handle_metrics),
            web.get("/logs", self.handle_logs),
            web.get("/network_graph", self.handle_network_graph),
            web.get("/network_graph_dataframe", self.handle_network_graph_dataframe),
        ])

    async def handle_metrics(self, request: web.Request) -> web.Response:
        # Get real data from Fritz!Box
        try:
            router_data = self.fritz_client.get_wan_stats()
            wlan_stats = self.fritz_client.get_wlan_traffic_stats()
            nodes, devices = self.discovery.discover()
            log_stats = self.log_collector.get_log_stats()
            
            self.exporter.update_from_snapshot(router_data, wlan_stats, nodes, devices)
            self.exporter.update_log_metrics(log_stats)
        except Exception as e:
            print(f"Error collecting metrics: {e}")
            # Return empty metrics on error
            router_data = {}
            wlan_stats = {}
            nodes, devices = [], []
            log_stats = {'total': 0}
            self.exporter.update_from_snapshot(router_data, wlan_stats, nodes, devices)
            self.exporter.update_log_metrics(log_stats)
        
        return web.Response(
            body=self.exporter.render(),
            content_type="text/plain",
        )

    async def handle_logs(self, request: web.Request) -> web.Response:
        """Expose logs in JSON format for Loki/Promtail."""
        try:
            import json
            logs = self.log_collector.get_logs()
            
            # Convert to JSON Lines format for easy consumption
            log_lines = []
            for log in logs:
                log_lines.append(json.dumps({
                    'timestamp': log.timestamp.isoformat(),
                    'message': log.message,
                    'severity': log.severity,
                    'source': log.source or '',
                    'category': log.category or '',
                }))
            
            return web.Response(
                body='\n'.join(log_lines),
                content_type="application/x-ndjson",
            )
        except Exception as e:
            print(f"Error fetching logs: {e}")
            return web.Response(
                body='{"error": "Failed to fetch logs"}',
                content_type="application/json",
                status=500,
            )

    async def handle_network_graph(self, request: web.Request) -> web.Response:
        """Expose network topology as JSON for Grafana NodeGraph."""
        try:
            import json
            nodes, devices = self.discovery.discover()
            
            # Build graph structure
            graph_nodes = []
            graph_edges = []
            edge_counter = 0
            
            for node in nodes:
                # Determine node type
                node_type = "router" if node.is_router else ("repeater" if node.is_repeater else ("powerline" if node.is_powerline else "unknown"))
                
                # Add node
                graph_nodes.append({
                    "id": node.mac,
                    "title": node.name,
                    "subTitle": node_type,
                    "mainStat": node.ip or "",
                })
                
                # Add edge if node has a parent
                if hasattr(node, 'parent_node') and node.parent_node:
                    edge_counter += 1
                    graph_edges.append({
                        "id": f"edge_{edge_counter}",
                        "source": node.parent_node.mac if hasattr(node.parent_node, 'mac') else node.parent_node,
                        "target": node.mac,
                    })
            
            response_data = {
                "nodes": graph_nodes,
                "edges": graph_edges
            }
            
            return web.Response(
                body=json.dumps(response_data, indent=2),
                content_type="application/json",
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET',
                    'Access-Control-Allow-Headers': 'Content-Type'
                }
            )
        except Exception as e:
            print(f"Error generating network graph: {e}")
            import traceback
            traceback.print_exc()
            return web.Response(
                body=json.dumps({"error": str(e), "nodes": [], "edges": []}),
                content_type="application/json",
                status=500,
            )

    async def handle_network_graph_dataframe(self, request: web.Request) -> web.Response:
        """Return network topology in Grafana Arrow format for nodeGraph."""
        try:
            nodes, _ = self.discovery.discover()
            
            # Build combined node-edge table
            rows = []
            
            for node in nodes:
                node_type = "router" if node.is_router else ("repeater" if node.is_repeater else "powerline")
                
                # Add row for this node and its edge
                if hasattr(node, 'parent_node') and node.parent_node:
                    parent_mac = node.parent_node.mac if hasattr(node.parent_node, 'mac') else str(node.parent_node)
                    rows.append({
                        "id": node.mac,
                        "title": node.name,
                        "subTitle": node_type,
                        "mainStat": node.ip or "",
                        "arc__source": parent_mac,
                        "arc__target": node.mac
                    })
                else:
                    # Root node (no parent)
                    rows.append({
                        "id": node.mac,
                        "title": node.name,
                        "subTitle": node_type,
                        "mainStat": node.ip or "",
                        "arc__source": "",
                        "arc__target": ""
                    })
            
            return web.Response(
                body=json.dumps(rows),
                content_type="application/json",
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET',
                    'Access-Control-Allow-Headers': 'Content-Type'
                }
            )
        except Exception as e:
            print(f"Error generating network graph dataframe: {e}")
            import traceback
            traceback.print_exc()
            return web.Response(
                body=json.dumps([]),
                content_type="application/json",
                status=500,
            )

    async def run(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.settings.exporter_host, self.settings.exporter_port)
        await site.start()
        print(f"Serving metrics on http://{self.settings.exporter_host}:{self.settings.exporter_port}/metrics")
        import asyncio
        while True:
            await asyncio.sleep(3600)
