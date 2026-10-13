#!/usr/bin/env bash
set -euo pipefail
# All network changes are confined to four namespaces owned by this CI run.
ci_nat_root=$(mktemp -d "${RUNNER_TEMP:-/tmp}/ziokt-nat.XXXXXX")
ci_nat_tag=${GITHUB_RUN_ID:-$$}
ci_nat_a="za-${ci_nat_tag}";ci_nat_r1="zr1-${ci_nat_tag}";ci_nat_r2="zr2-${ci_nat_tag}";ci_nat_w="zw-${ci_nat_tag}"
ci_nat_pid=""
cleanup() {
 if [[ -n "$ci_nat_pid" ]]; then kill "$ci_nat_pid" 2>/dev/null || true;wait "$ci_nat_pid" 2>/dev/null || true;fi
 for ns in "$ci_nat_a" "$ci_nat_r1" "$ci_nat_r2" "$ci_nat_w";do ip netns del "$ns" 2>/dev/null || true;done
 rm -rf -- "$ci_nat_root"
}
trap cleanup EXIT
for ns in "$ci_nat_a" "$ci_nat_r1" "$ci_nat_r2" "$ci_nat_w";do ip netns add "$ns";ip -n "$ns" link set lo up;done
ip link add za0 type veth peer name zrl0
ip link set za0 netns "$ci_nat_a";ip link set zrl0 netns "$ci_nat_r1"
ip link add zrw0 type veth peer name zrl1
ip link set zrw0 netns "$ci_nat_r1";ip link set zrl1 netns "$ci_nat_r2"
ip link add zrw1 type veth peer name zw0
ip link set zrw1 netns "$ci_nat_r2";ip link set zw0 netns "$ci_nat_w"
ip -n "$ci_nat_a" addr add 10.241.1.2/24 dev za0;ip -n "$ci_nat_a" link set za0 up
ip -n "$ci_nat_r1" addr add 10.241.1.1/24 dev zrl0;ip -n "$ci_nat_r1" link set zrl0 up
ip -n "$ci_nat_r1" addr add 172.30.241.2/24 dev zrw0;ip -n "$ci_nat_r1" link set zrw0 up
ip -n "$ci_nat_r2" addr add 172.30.241.1/24 dev zrl1;ip -n "$ci_nat_r2" link set zrl1 up
ip -n "$ci_nat_r2" addr add 198.18.241.2/24 dev zrw1;ip -n "$ci_nat_r2" link set zrw1 up
ip -n "$ci_nat_w" addr add 198.18.241.1/24 dev zw0;ip -n "$ci_nat_w" link set zw0 up
ip -n "$ci_nat_a" route add default via 10.241.1.1
ip -n "$ci_nat_r1" route add default via 172.30.241.1
for ns in "$ci_nat_r1" "$ci_nat_r2";do
 ip netns exec "$ns" sysctl -q -w net.ipv4.ip_forward=1
 ip netns exec "$ns" iptables -P FORWARD DROP
 ip netns exec "$ns" iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
done
ip netns exec "$ci_nat_r1" iptables -A FORWARD -i zrl0 -o zrw0 -j ACCEPT
ip netns exec "$ci_nat_r1" iptables -t nat -A POSTROUTING -o zrw0 -j MASQUERADE
ip netns exec "$ci_nat_r2" iptables -A FORWARD -i zrl1 -o zrw1 -j ACCEPT
ip netns exec "$ci_nat_r2" iptables -t nat -A POSTROUTING -o zrw1 -j MASQUERADE
python3 ci/nat_peer.py prepare "$ci_nat_root"
ip netns exec "$ci_nat_w" python3 ci/nat_peer.py serve "$ci_nat_root" >"$ci_nat_root/relay.log" 2>&1 &
ci_nat_pid=$!
for attempt in $(seq 1 100);do [[ -f "$ci_nat_root/ready" ]] && break;sleep .1;done
[[ -f "$ci_nat_root/ready" ]]
ip netns exec "$ci_nat_a" python3 ci/nat_peer.py send "$ci_nat_root"
ip -n "$ci_nat_a" addr del 10.241.1.2/24 dev za0
ip -n "$ci_nat_a" addr add 10.241.1.3/24 dev za0
ip -n "$ci_nat_r2" addr del 198.18.241.2/24 dev zrw1
ip -n "$ci_nat_r2" addr add 198.18.241.3/24 dev zrw1
ip netns exec "$ci_nat_a" python3 ci/nat_peer.py receive "$ci_nat_root"
for ns in "$ci_nat_r1" "$ci_nat_r2";do
 ip netns exec "$ns" iptables -t nat -L POSTROUTING -n -v
 ip netns exec "$ns" iptables -L FORWARD -n -v
done
