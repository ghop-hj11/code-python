import ipaddress
import json
import socket
import subprocess
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def input_int(prompt, min_value=None, max_value=None, default=None):
    while True:
        text = input(prompt).strip()
        if not text and default is not None:
            return default
        if not text.isdigit():
            print("请输入有效整数。")
            continue
        value = int(text)
        if min_value is not None and value < min_value:
            print(f"输入值必须大于等于 {min_value}。")
            continue
        if max_value is not None and value > max_value:
            print(f"输入值必须小于等于 {max_value}。")
            continue
        return value


def port_detection():
    target = input("target ip or hostname: ").strip()
    if not target:
        print("目标不能为空。")
        return

    end_port = input_int("port: ", min_value=1, max_value=65535)

    try:
        socket.gethostbyname(target)
    except socket.gaierror:
        print("无法解析目标地址。")
        return

    start_port = 1
    threads = 200
    timeout = 1.0

    def scan_port(port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                if s.connect_ex((target, port)) == 0:
                    return port
        except OSError:
            pass
        return None

    print(f"开始扫描 {target}，端口范围 {start_port}-{end_port} ...")
    open_ports = []

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(scan_port, port): port for port in range(start_port, end_port + 1)}
        for future in as_completed(futures):
            port = future.result()
            if port:
                open_ports.append(port)
                print(f"[+] 发现开放端口: {port}")

    if open_ports:
        print(f"\n扫描完成！开放端口列表: {sorted(open_ports)}")
    else:
        print("\n扫描完成，未发现开放端口。")


def passive_info_collection():
    def parse_os_from_cpe(cpe_list):
        os_set = set()
        for cpe in cpe_list:
            parts = cpe.split(":")
            if len(parts) >= 4 and parts[1] == "o":
                os_set.add(f"{parts[2]} {parts[3]}".strip())
        return sorted(os_set) if os_set else None

    def parse_os_from_tags(tags):
        os_hints = {tag[3:] for tag in tags if tag.startswith("os:")}
        return sorted(os_hints) if os_hints else None

    def query_shodan(ip):
        url = f"https://internetdb.shodan.io/{ip}"
        req = Request(url, headers={"User-Agent": "PassiveRecon/1.0"})
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 404:
                print(f"[!] Shodan 中未找到 {ip} 的记录")
            else:
                print(f"[!] HTTP 错误 {e.code}: {e.reason}")
            return None
        except URLError as e:
            print(f"[!] 网络连接错误: {e.reason}")
            return None

    def print_ports(ports):
        if not ports:
            print("  无开放端口记录")
            return
        print(f"{'端口':<8} {'协议':<6} {'服务'}")
        print("-" * 30)
        for p in ports:
            print(f"{p['port']:<8} {p.get('transport', 'tcp'):<6} {p.get('service', '?')}")

    target = input("请输入目标 IP 或域名: ").strip()
    if not target:
        print("[!] 输入为空，退出。")
        return

    try:
        socket.inet_aton(target)
        ip = target
    except OSError:
        try:
            ip = socket.gethostbyname(target)
            print(f"[*] 域名 {target} 解析为 IP: {ip}\n")
        except socket.gaierror:
            print(f"[!] 无法解析域名: {target}")
            return

    print(f"[*] 正在查询 {ip} ...\n")
    data = query_shodan(ip)
    if data is None:
        return

    print("=" * 50)
    print(f"目标 IP      : {ip}")
    hostnames = data.get("hostnames", [])
    print(f"主机名       : {', '.join(hostnames) if hostnames else '无'}")
    print(f"国家/地区    : {data.get('country_name', '未知')} ({data.get('country_code', '')})")
    print(f"组织         : {data.get('org', '未知')}")
    print("-" * 50)

    print("[操作系统]")
    os_cpe = parse_os_from_cpe(data.get("cpes", []))
    os_tags = parse_os_from_tags(data.get("tags", []))
    if os_cpe:
        print(f"  CPE 识别 OS : {', '.join(os_cpe)}")
    if os_tags:
        print(f"  标签提示 OS : {', '.join(os_tags)}")
    if not os_cpe and not os_tags:
        print("  未能识别操作系统")

    print("-" * 50)
    print("[开放端口与服务]")
    print_ports(data.get("ports", []))

    print("-" * 50)
    vulns = data.get("vulns", [])
    if vulns:
        print(f"[漏洞] 共 {len(vulns)} 个")
        for v in vulns[:5]:
            print(f"  - {v}")
    else:
        print("[漏洞] 无已知漏洞记录")
    print("=" * 50)


def equipment_detection():
    def get_local_network():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(1)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
        except Exception:
            local_ip = socket.gethostbyname(socket.gethostname())
            if local_ip.startswith("127."):
                print("无法自动检测本机局域网 IP，请手动指定网段（如 192.168.1.0/24）")
                return None

        parts = local_ip.split(".")
        network_str = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        try:
            return ipaddress.IPv4Network(network_str, strict=False)
        except ValueError as e:
            print(f"网段生成错误: {e}")
            return None

    def ping_host(ip_str):
        is_windows = sys.platform.lower().startswith("win")
        param = "-n" if is_windows else "-c"
        timeout_param = "-w" if is_windows else "-W"
        timeout_value = "500" if is_windows else "1"
        cmd = ["ping", param, "1", timeout_param, timeout_value, ip_str]
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return ip_str, result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return ip_str, False

    def scan_network(network, max_workers=100):
        hosts = list(network.hosts())
        print(f"开始扫描网段 {network}，共 {len(hosts)} 个主机地址...")
        alive_ips = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ip = {executor.submit(ping_host, str(ip)): ip for ip in hosts}
            for future in as_completed(future_to_ip):
                ip, is_alive = future.result()
                if is_alive:
                    alive_ips.append(ip)
                    print(f"  发现存活主机: {ip}")
        return alive_ips

    print("=== 局域网开机设备扫描器 ===\n")
    network = get_local_network()
    if network is None:
        return

    print(f"检测到本机网段: {network} (假设子网掩码 255.255.255.0)")
    if input("\n按 Enter 开始扫描（或输入其他内容退出）: ").strip():
        print("已取消扫描。")
        return

    alive = scan_network(network)
    print(f"\n扫描完成。存活主机数量: {len(alive)}")
    if alive:
        print("存活主机列表:")
        for ip in sorted(alive, key=lambda x: ipaddress.IPv4Address(x)):
            print(f"  {ip}")
    else:
        print("未发现任何开机设备（可能防火墙禁 ping 或网段设置不正确）。")


def main():
    print("1. port detection")
    print("2. passive information collection")
    print("3. equipment detection")
    print("4. join us")

    option = input_int("选择功能编号: ", min_value=1, max_value=4)

    if option == 1:
        port_detection()
    elif option == 2:
        passive_info_collection()
    elif option == 3:
        equipment_detection()
    elif option == 4:
        print("欢迎加入我们！请访问以下链接了解更多信息：")
        webbrowser.open("http://11110.cloud/static_web/6a7acd4e09e6e7.15080530.html")


if __name__ == "__main__":
    main()
