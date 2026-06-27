# Container Validation

All commands run from the repo root after `docker compose up --build -d`.

## 1. Start the system

```bash
docker compose up --build -d
```

```
[+] Running 5/5
 ✔ Network group-seven-devops_internal       Created
 ✔ Container group-seven-devops-service-b-1  Started
 ✔ Container group-seven-devops-service-c-1  Started
 ✔ Container group-seven-devops-service-a-1  Started
 ✔ Container group-seven-devops-nginx-1      Started
```

## 2. Confirm containers are running

```bash
docker compose ps
```

```
NAME                             IMAGE                          SERVICE     STATUS        PORTS
group-seven-devops-nginx-1       nginx:alpine                   nginx       Up            0.0.0.0:8080->80/tcp
group-seven-devops-service-a-1   group-seven-devops-service-a   service-a   Up
group-seven-devops-service-b-1   group-seven-devops-service-b   service-b   Up
group-seven-devops-service-c-1   group-seven-devops-service-c   service-c   Up
```

Only Nginx publishes a host port. Services B and C have none.

## 3. Test public entry point

```bash
curl -i http://localhost:8080/service-a/health
```

```
HTTP/1.1 200 OK
{"message":"Hello service-a listening on 3001","port":3001,"service":"service-a","status":"healthy"}
```

## 4. Prove B and C are not directly exposed

```bash
curl -i --connect-timeout 3 http://localhost:3002/health
curl -i --connect-timeout 3 http://localhost:3003/health
```

```
curl: (7) Failed to connect to localhost port 3002 after 0 ms: Connection refused
curl: (7) Failed to connect to localhost port 3003 after 0 ms: Connection refused
```

## 5. Prove internal service discovery works

```bash
docker compose exec service-a curl -i http://service-b:3002/health
docker compose exec service-b curl -i http://service-c:3003/health
```

```
HTTP/1.1 200 OK
{"message":"Hello service-b listening on 3002","port":3002,"service":"service-b","status":"healthy"}

HTTP/1.1 200 OK
{"message":"Hello service-c listening on 3003","port":3003,"service":"service-c","status":"healthy"}
```

Services reach each other using Compose DNS names — no hardcoded IPs.

## 6. Trace one request

```bash
curl -i http://localhost:8080/service-a/greet-service-b -H "X-Request-ID: demo-container-001"
docker compose logs | grep demo-container-001
```

```
HTTP/1.1 200 OK
{"message":"Request completed successfully","request_id":"demo-container-001","status":"success"}
```

Log trace across all four services:

```
nginx-1      | {"timestamp":"2026-06-27T03:24:16+00:00","service":"nginx","request_id":"demo-container-001","method":"GET","uri":"/service-a/greet-service-b","status":200,"remote_addr":"172.18.0.1","upstream":"172.18.0.4:3001","response_time":0.010}
service-a-1  | {"timestamp":"2026-06-27T03:24:16.382493Z","service":"service-a","event":"request_received","request_id":"demo-container-001","method":"GET","path":"/greet-service-b","status":200}
service-b-1  | {"timestamp":"2026-06-27T03:24:16.384376Z","service":"service-b","event":"request_received","request_id":"demo-container-001","method":"GET","path":"/greet","status":200}
service-c-1  | {"timestamp":"2026-06-27T03:24:16.386024Z","service":"service-c","event":"request_received","request_id":"demo-container-001","method":"GET","path":"/greet-c","status":200}
service-c-1  | {"timestamp":"2026-06-27T03:24:16.388597Z","service":"service-c","event":"callback_sent","request_id":"demo-container-001","target":"service-a","status":200}
service-a-1  | {"timestamp":"2026-06-27T03:24:16.390779Z","service":"service-a","event":"downstream_call_success","request_id":"demo-container-001","target":"service-b","status":200}
service-a-1  | {"timestamp":"2026-06-27T03:24:16.390826Z","service":"service-a","event":"request_complete","request_id":"demo-container-001","status":200}
```

The same request ID appears in Nginx, Service A, Service B, and Service C.

## 7. Stop Service B and observe failure

```bash
docker compose stop service-b
curl -i http://localhost:8080/service-a/greet-service-b -H "X-Request-ID: fail-service-b-001"
docker compose logs service-a | grep fail-service-b-001
```

```
HTTP/1.1 500 INTERNAL SERVER ERROR
{"error":"HTTPConnectionPool(host='service-b', port=3002): Max retries exceeded with url: /greet (Caused by NameResolutionError(...))"}
```

Service A logged the failure:

```
service-a-1 | {"timestamp":"2026-06-27T03:32:04.884731Z","service":"service-a","event":"request_received","request_id":"fail-service-b-001","method":"GET","path":"/greet-service-b","status":200}
service-a-1 | {"timestamp":"2026-06-27T03:32:04.969811Z","service":"service-a","event":"downstream_call_failed","request_id":"fail-service-b-001","target":"service-b","error":"...Failed to resolve 'service-b'...","status":500}
```

Recover:

```bash
docker compose start service-b
curl -i http://localhost:8080/service-a/greet-service-b -H "X-Request-ID: recover-001"
```

```
HTTP/1.1 200 OK
{"message":"Request completed successfully","request_id":"recover-001","status":"success"}
```

Full flow restored after Service B restarted.

## 8. View logs per service

```bash
docker compose logs nginx
docker compose logs service-a
docker compose logs service-b
docker compose logs service-c
```

All logs are JSON-structured and written to stdout, visible via `docker compose logs`.

## 9. Shut everything down

```bash
docker compose down
```
