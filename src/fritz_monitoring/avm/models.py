from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class Node:
    """Represents a Fritz! device in the mesh (router, repeater, powerline)."""
    name: str
    mac: str
    ip: Optional[str]
    is_router: bool
    is_repeater: bool
    is_powerline: bool
    extra: Dict[str, Any]
    parent_node: Optional[str] = None  # Name of parent node in mesh hierarchy

@dataclass
class Device:
    """Represents a client device (phone, TV, Alexa, etc.)."""
    name: str
    mac: str
    ip: Optional[str]
    online: bool
    interface_type: Optional[str]  # wlan/lan/guest
    connected_node: Optional[str]  # Node name/MAC
    rx_bytes_total: Optional[int] = None
    tx_bytes_total: Optional[int] = None
    extra: Dict[str, Any] = None
