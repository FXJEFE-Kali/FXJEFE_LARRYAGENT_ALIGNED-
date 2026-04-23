#!/usr/bin/env python3
"""Test device tracking functionality."""
import sys
sys.path.insert(0, '.')
from mcp_servers.network_monitor_server import NetworkMonitorServer

def main():
    monitor = NetworkMonitorServer()

    print("=" * 60)
    print("DEVICE TRACKING TEST")
    print("=" * 60)

    # 1. Scan network devices
    print("\n[1] SCANNING NETWORK DEVICES...")
    devices = monitor.scan_network_devices()
    print("Subnet:", devices.get("subnet", "?"))
    print("Devices found:", devices.get("devices_found", 0))

    for d in devices.get("devices", [])[:10]:
        ip = d.get("IP", "?")
        mac = d.get("MAC", "?")
        iface = d.get("Interface", "?")
        state = d.get("State", "?")
        print(f"   {ip:15} | {mac:17} | {iface} ({state})")

    # 2. Detect new devices
    print("\n[2] DETECTING NEW DEVICES...")
    new = monitor.detect_new_devices()
    print("Total devices:", new.get("total_devices", 0))
    print("New devices:", new.get("new_devices_count", 0))

    if new.get("new_devices"):
        print("NEW DEVICES DETECTED:")
        for nd in new.get("new_devices", []):
            ip = nd.get("ip", "?")
            mac = nd.get("mac", "?")
            print(f"   NEW: {ip} | {mac}")

    if new.get("alert"):
        print("ALERT:", new.get("alert"))

    # 3. Test approve devices (if any real devices found)
    print("\n[3] TESTING APPROVE/BLOCK...")
    
    # Approve router (10.0.0.1) and gateway (10.0.0.138) if they exist
    first_seen = monitor.get_known_devices().get("first_seen", {})
    
    # Find and approve router
    router_mac = None
    gateway_mac = None
    for mac, info in first_seen.items():
        ip = info.get("ip", "")
        if ip == "10.0.0.1":
            router_mac = mac
        elif ip == "10.0.0.138":
            gateway_mac = mac
    
    if router_mac:
        result = monitor.approve_device(router_mac, "Main Router")
        print(f"Approved router ({router_mac}): {result.get('success')}")
    
    if gateway_mac:
        result = monitor.approve_device(gateway_mac, "Network Gateway")
        print(f"Approved gateway ({gateway_mac}): {result.get('success')}")

    # 4. Get known devices
    print("\n[4] KNOWN DEVICES STATUS...")
    known = monitor.get_known_devices()
    print("Approved:", known.get("approved_count", 0))
    print("Blocked:", known.get("blocked_count", 0))
    print("Total seen:", known.get("total_seen", 0))

    # Show approved devices
    approved = known.get("approved", {})
    if approved:
        print("\nApproved devices:")
        for mac, info in approved.items():
            name = info.get("name", "?")
            ip = info.get("ip", "?")
            print(f"   OK {ip:15} | {mac} | {name}")

    # Show first_seen devices
    first_seen = known.get("first_seen", {})
    if first_seen:
        print("\nAll devices seen on network:")
        for mac, info in list(first_seen.items())[:8]:
            ip = info.get("ip", "?")
            when = info.get("first_seen", "?")[:19]
            print(f"   {ip:15} | {mac} | First seen: {when}")

    # 5. Get device log
    print("\n[5] DEVICE ACTIVITY LOG...")
    log = monitor.get_device_log(lines=10)
    print("Total entries:", log.get("total_entries", 0))
    for entry in log.get("entries", [])[-5:]:
        print("  ", entry)

    # 6. Run detection again
    print("\n[6] RUNNING DETECTION AGAIN (should find fewer new)...")
    new2 = monitor.detect_new_devices()
    print("New devices now:", new2.get("new_devices_count", 0))
    if new2.get("new_devices_count", 0) == 0:
        print("All devices are now known!")

    print("\n" + "=" * 60)
    print("DEVICE TRACKING TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
