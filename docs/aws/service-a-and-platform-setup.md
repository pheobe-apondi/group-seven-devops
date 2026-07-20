# Service A + Platform Setup — CLI Reference

Owner: Pheobe — Service A and Platform (cluster, namespace, ALB, target group, CodeConnections).

Run these in order. Each command tags resources with the four required tags
(`Project=devops-mentorship`, `Group=group-7`, `Environment=lab`, `Owner=<role>`) where the AWS
API supports tagging at creation time.

---

## 0. Shared environment variables

Set these once per shell session before running anything below.

**Before running anything below:** each team member configures their own named CLI profile with
their own IAM access keys, rather than the shell's `default` profile — this avoids clobbering a
personal/work AWS profile that may already exist on that machine. Anyone on the team, regardless of
which service they own, does this once:

```bash
aws configure --profile devops-g7
# Enter that IAM user's own access key ID + secret access key (from the IAM console,
# not a teammate's), region eu-west-2, output format json.

# Verify it resolves to the lab account (827478161993) under the expected IAM user, not a work account:
aws sts get-caller-identity --profile devops-g7
```

Then, for the rest of a terminal session:

```bash
export AWS_PROFILE=devops-g7
export AWS_DEFAULT_REGION=eu-west-2
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

export VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

# Two default subnets in different AZs (required for the ALB + ECS service)
export SUBNET_IDS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[].SubnetId' --output text)
SUBNET_ARRAY=($SUBNET_IDS)
export SUBNET_1=${SUBNET_ARRAY[0]}
export SUBNET_2=${SUBNET_ARRAY[1]}

echo "VPC: $VPC_ID | Subnets: $SUBNET_1 $SUBNET_2 | Account: $ACCOUNT_ID"
```

---

## 1. Security groups (Platform creates ALB SG; Service A owner creates its own SG)

```bash
# ALB security group — platform owner
ALB_SG_ID=$(aws ec2 create-security-group \
  --group-name devops-g7-alb-sg \
  --description "Internet-facing ALB SG for devops-g7" \
  --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=devops-mentorship},{Key=Group,Value=group-7},{Key=Owner,Value=platform-owner},{Key=Environment,Value=lab},{Key=Name,Value=devops-g7-alb-sg}]' \
  --query 'GroupId' --output text)

aws ec2 authorize-security-group-ingress --group-id $ALB_SG_ID \
  --protocol tcp --port 80 --cidr 0.0.0.0/0

# Service A security group — service-a owner
SVC_A_SG_ID=$(aws ec2 create-security-group \
  --group-name devops-g7-service-a-sg \
  --description "Service A task SG for devops-g7" \
  --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=devops-mentorship},{Key=Group,Value=group-7},{Key=Owner,Value=service-a-owner},{Key=Environment,Value=lab},{Key=Name,Value=devops-g7-service-a-sg}]' \
  --query 'GroupId' --output text)

# Only the ALB may reach service-a, on the app port (3001) — SG reference, not CIDR
aws ec2 authorize-security-group-ingress --group-id $SVC_A_SG_ID \
  --protocol tcp --port 3001 --source-group $ALB_SG_ID

# service-c -> service-a on 3001 for the /greeting-rcvd callback (added once Mercylin's
# service-c-sg exists — coordinate the SG ID with Mercylin before running this):
# aws ec2 authorize-security-group-ingress --group-id $SVC_A_SG_ID \
#   --protocol tcp --port 3001 --source-group $SVC_C_SG_ID

echo "ALB_SG_ID=$ALB_SG_ID"
echo "SVC_A_SG_ID=$SVC_A_SG_ID"
```

---

## 2. ECS cluster (Platform)

```bash
aws ecs create-cluster \
  --cluster-name devops-g7-cluster \
  --capacity-providers FARGATE \
  --tags key=Project,value=devops-mentorship key=Group,value=group-7 \
         key=Owner,value=platform-owner key=Environment,value=lab
```

---

## 2A. CodeConnections — GitHub connection (Platform)

**Status: done.** Created via console (the GitHub OAuth handshake isn't scriptable end-to-end;
see AWS Console → Developer Tools → Connections → Create connection → GitHub, installed the AWS
Connector for GitHub app scoped to only the `group-seven-devops` repo).

- Name: `devops-g7-github-connection`
- Status: `Available`
- ARN (needed later for CodePipeline's source stage):
  ```
  arn:aws:codeconnections:eu-west-2:827478161993:connection/4dc56f2a-9851-4938-be15-935882d6fdf4
  ```
- Tags: `Project=devops-mentorship`, `Group=group-7`, `Owner=platform-owner`, `Environment=lab`

---

## 3. Service Connect namespace (Platform)

```bash
aws servicediscovery create-http-namespace \
  --name g7.internal \
  --tags Key=Project,Value=devops-mentorship Key=Group,Value=group-7 \
         Key=Owner,Value=platform-owner Key=Environment,Value=lab
```

---

## 4. ECR repository (Service A owner)

```bash
aws ecr create-repository \
  --repository-name devops-g7-service-a \
  --image-tag-mutability IMMUTABLE \
  --tags Key=Project,Value=devops-mentorship Key=Group,Value=group-7 \
         Key=Owner,Value=service-a-owner Key=Environment,Value=lab
```

---

## 5. IAM roles (Service A owner needs these to register the task definition)

```bash
# Trust policy shared by execution + task roles
cat > /tmp/ecs-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

# Execution role — image pull + logging (shared across services if platform creates it once;
# otherwise each service owner creates their own devops-g7-<service>-execution-role)
aws iam create-role \
  --role-name devops-g7-ecs-execution-role \
  --assume-role-policy-document file:///tmp/ecs-trust-policy.json

aws iam attach-role-policy \
  --role-name devops-g7-ecs-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Task role for service-a — needed for ECS Exec (SSM messaging)
aws iam create-role \
  --role-name devops-g7-service-a-task-role \
  --assume-role-policy-document file:///tmp/ecs-trust-policy.json

cat > /tmp/ecs-exec-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel"
    ],
    "Resource": "*"
  }]
}
EOF

aws iam put-role-policy \
  --role-name devops-g7-service-a-task-role \
  --policy-name devops-g7-ecs-exec-policy \
  --policy-document file:///tmp/ecs-exec-policy.json
```

---

## 6. Build and push the first image (manual, before the pipeline exists)

```bash
aws ecr get-login-password --region $AWS_DEFAULT_REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com

COMMIT_SHA=$(git rev-parse --short=7 HEAD)
IMAGE_URI=$ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/devops-g7-service-a:$COMMIT_SHA

docker build -t $IMAGE_URI -f services/service-a/Dockerfile .
docker push $IMAGE_URI

echo "IMAGE_URI=$IMAGE_URI"
```

**CPU/memory justification:** 256 CPU units (.25 vCPU) / 512 MB. Service A is a single-threaded-per-request
Flask dev server doing lightweight I/O (proxying to B, waiting on a callback) with no CPU-bound work,
and the lab's traffic is a handful of requests/sec at most — this is Fargate's smallest valid
combination for that CPU value. Revisit under `scripts/load-test.sh` load if p95 latency or OOM-kills
show up in CloudWatch.

## 7. Register the task definition

Fill `<ACCOUNT_ID>` and `<COMMIT_SHA>` in `ecs/service-a-task-definition.json` (or `envsubst`
it), then:

```bash
sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" -e "s|<COMMIT_SHA>|$COMMIT_SHA|g" \
  ecs/service-a-task-definition.json > /tmp/service-a-task-definition.rendered.json

aws ecs register-task-definition --cli-input-json file:///tmp/service-a-task-definition.rendered.json
```

---

## 8. ALB, target group, listener (Platform)

```bash
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name devops-g7-alb \
  --subnets $SUBNET_1 $SUBNET_2 \
  --security-groups $ALB_SG_ID \
  --scheme internet-facing --type application \
  --tags Key=Project,Value=devops-mentorship Key=Group,Value=group-7 \
         Key=Owner,Value=platform-owner Key=Environment,Value=lab \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)

TG_ARN=$(aws elbv2 create-target-group \
  --name devops-g7-service-a-tg \
  --protocol HTTP --port 3001 \
  --vpc-id $VPC_ID --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 15 \
  --tags Key=Project,Value=devops-mentorship Key=Group,Value=group-7 \
         Key=Owner,Value=platform-owner Key=Environment,Value=lab \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN

ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)
echo "ALB_DNS=$ALB_DNS"
```

---

## 9. ECS service for Service A (with Service Connect + ALB registration)

```bash
aws ecs create-service \
  --cluster devops-g7-cluster \
  --service-name devops-g7-service-a-svc \
  --task-definition devops-g7-service-a-task \
  --desired-count 2 \
  --launch-type FARGATE \
  --platform-version LATEST \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$SVC_A_SG_ID],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=service-a,containerPort=3001" \
  --service-connect-configuration '{
    "enabled": true,
    "namespace": "g7.internal",
    "services": [{
      "portName": "service-a",
      "discoveryName": "service-a",
      "clientAliases": [{ "port": 3001, "dnsName": "service-a" }]
    }]
  }' \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --enable-execute-command \
  --tags key=Project,value=devops-mentorship key=Group,value=group-7 \
         key=Owner,value=service-a-owner key=Environment,value=lab
```

---

## 10. Verify

```bash
# Public request through the ALB (replaces the old /service-a/health path — no nginx prefix anymore)
curl -i http://$ALB_DNS/health

# Task state
aws ecs describe-services --cluster devops-g7-cluster --services devops-g7-service-a-svc \
  --query 'services[0].{status:status,running:runningCount,desired:desiredCount}'

# ECS Exec into a running task
TASK_ARN=$(aws ecs list-tasks --cluster devops-g7-cluster --service-name devops-g7-service-a-svc \
  --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster devops-g7-cluster --task $TASK_ARN \
  --container service-a --interactive --command "/bin/sh"
```

Once Mercylin's service-b and service-c are registered under the same `g7.internal` namespace with
discovery names `service-b`/`service-c`, `curl http://<alb-dns>/greet-service-b` should trigger the
full A→B→C→callback flow with no code changes on either side.

---

## Live resource record (as actually deployed)

| Resource | Value |
|---|---|
| ALB DNS | `devops-g7-alb-2100544488.eu-west-2.elb.amazonaws.com` |
| ALB ARN | `arn:aws:elasticloadbalancing:eu-west-2:827478161993:loadbalancer/app/devops-g7-alb/168a47b8333e98cf` |
| Target group ARN | `arn:aws:elasticloadbalancing:eu-west-2:827478161993:targetgroup/devops-g7-service-a-tg/d12ce60e33b072b3` |
| ECS cluster | `devops-g7-cluster` |
| ECS service | `devops-g7-service-a-svc` (desired 2, running 2, both targets healthy) |
| Task definition | `devops-g7-service-a-task:1` |
| ECR image | `827478161993.dkr.ecr.eu-west-2.amazonaws.com/devops-g7-service-a:4fa0583` |
| Service Connect namespace | `g7.internal` (`ns-uijmzcpru6oqmjvg`) |
| Execution role | `arn:aws:iam::827478161993:role/devops-g7-ecs-execution-role` |
| Task role | `arn:aws:iam::827478161993:role/devops-g7-service-a-task-role` |
| ALB SG | `sg-0582d630f9527972f` |
| Service A SG | `sg-063ca47f1fda210e9` |

**Verified 2026-07-20:** `curl -i http://<alb-dns>/health` → `200 OK`,
`{"dependencies":{"service-b":"unreachable"},"port":3001,"service":"service-a","status":"degraded"}`.
`degraded` is expected until service-b exists — this response proves service-a's own health check,
Fargate networking, ALB routing, and Service Connect's Envoy sidecar (see `server: envoy` response
header) are all working correctly in isolation.

**Still outstanding for Service A's part specifically:**
- The `service-c → service-a` SG rule for the `/greeting-rcvd` callback (needs Mercylin's
  `service-c-sg` ID)
- CodePipeline + CodeBuild project for Service A (source → build → ECR push → ECS deploy), so
  merges to `main` deploy automatically instead of the manual build/push/register done above
- Gate 2 negative tests (`Internet → service-a:3001` denied, `A → C` denied) once C exists
