# Task 5: subnetting 10.20.0.0/16 and the public-subnet NACL

## Subnet table

Allocated from the largest requirement to the smallest, starting at 10.20.0.0, each subnet directly after the previous one.

| Subnet | Hosts needed | Prefix | Network address | Usable host range | Broadcast | Usable hosts |
|---|---|---|---|---|---|---|
| app | 1,000 | /22 | 10.20.0.0 | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 250 | /24 | 10.20.4.0 | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 100 | /25 | 10.20.5.0 | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 20 | /27 | 10.20.5.128 | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

## Working

Usable hosts = 2^(32 − prefix) − 2. The smallest prefix whose usable hosts cover the requirement:

- **app (1,000):** /23 gives 2^9 − 2 = 510 (too few); /22 gives 2^10 − 2 = 1,022 ≥ 1,000. Block size 1,024 = 4 × 256.
  Starts at 10.20.0.0, so it covers 10.20.0.0 – 10.20.3.255. Broadcast 10.20.3.255.
- **public (250):** /25 gives 2^7 − 2 = 126 (too few); /24 gives 2^8 − 2 = 254 ≥ 250. Block size 256.
  Starts right after the app block, at 10.20.4.0, and ends at 10.20.4.255.
- **data (100):** /26 gives 2^6 − 2 = 62 (too few); /25 gives 2^7 − 2 = 126 ≥ 100. Block size 128.
  Starts at 10.20.5.0, ends at 10.20.5.127.
- **management (20):** /28 gives 2^4 − 2 = 14 (too few); /27 gives 2^5 − 2 = 30 ≥ 20. Block size 32.
  Starts at 10.20.5.128, ends at 10.20.5.159.

The four blocks use 10.20.0.0 – 10.20.5.159 and do not overlap. Everything from 10.20.5.160 to 10.20.255.255 is unallocated.
Each block starts at an offset (from 10.20.0.0) that is a multiple of its own size, as a valid network address must: app 0, public 1,024 = 4 × 256, data 1,280 = 10 × 128, management 1,408 = 44 × 32.

## NACL for the public subnet (`nacl.json`)

The load balancer lives in this subnet. Rules are evaluated from the lowest number upward; the first match decides; no match means deny.

**Inbound** (the CIDR matches the packet's source address)

| Rule | Action | Protocol / port | Source | Purpose |
|---|---|---|---|---|
| 100 | deny | all | 198.51.100.0/24 | known abusive range, blocked on every port |
| 110 | allow | TCP 80 | 0.0.0.0/0 | HTTP from anywhere |
| 120 | allow | TCP 443 | 0.0.0.0/0 | HTTPS from anywhere |
| 130 | allow | TCP 22 | 10.20.5.128/27 | SSH only from the management subnet |
| 140 | allow | TCP 1024–65535 | 10.20.0.0/22 | replies coming back from the app subnet (to the load balancer's ephemeral ports) |
| – | deny | | | implicit default |

**Outbound** (the CIDR matches the packet's destination address)

| Rule | Action | Protocol / port | Destination | Purpose |
|---|---|---|---|---|
| 100 | allow | TCP 8000 | 10.20.0.0/22 | load balancer to the service in the app subnet |
| 110 | allow | TCP 1024–65535 | 0.0.0.0/0 | replies back to clients, who use ephemeral ports 1024–65535 |
| – | deny | | | implicit default |

### Check with the simulator

```
python3 tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check   # 6 / 6 = 100%
python3 tools/nacl_sim.py network/nacl.json network/packets_extra.jsonl --check    # 23 / 23 = 100%
```

`packets_extra.jsonl` holds 23 extra packets I wrote (blocked range on ports 80, 443, 22 and an ephemeral port; SSH from inside and outside the management range; replies from the app subnet and from elsewhere; UDP; ports just below 1024; wrong outbound ports). Their expected values are my own reading of the requirements, not the marker's.

### Known limitation of the rules

Outbound rule 110 (TCP 1024–65535 to anywhere) also covers port 8000 and any other port in that range to any destination, and inbound rule 140 allows any TCP port 1024–65535 from the app subnet, not only replies. A stateless NACL sees only the destination port of each packet, so it cannot tell a reply from a new connection that happens to use a high port. The task wording ("replies going back to clients anywhere", clients on ports 1024–65535) leaves no tighter rule that would still be correct. In a real deployment the security groups (which are stateful) would carry the finer restrictions.

## Why replies need their own rules, and why rule order matters

A network ACL is stateless: it looks at every packet on its own and keeps no record of connections. When a client opens a connection to port 443, the request is checked against the inbound rules, but the reply travels in the other direction, from port 443 to the client's ephemeral port, and is checked against the outbound rules as if it were unrelated traffic. Without an outbound rule that allows TCP 1024–65535 to the clients, the replies would hit the default deny and the connection would hang even though the request was accepted. The same holds in the other direction: the load balancer's request to the app on port 8000 is allowed by the outbound rule, and the answer returns from the app subnet to the load balancer's ephemeral port, so it needs the inbound rule 140. This is different from a stateful security group, which allows the reply automatically.

Rules are evaluated from the lowest number upward and the first match decides, so the deny for 198.51.100.0/24 only works if its number is lower than the allow rules it must override. Rule 100 (deny) comes before rules 110 and 120 (allow TCP 80 and 443 from anywhere). A packet from 198.51.100.9 to port 443 matches the deny first and is dropped. If the deny were numbered 150, the same packet would match rule 120 first, be allowed, and the deny would never be reached.
