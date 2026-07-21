# Service B Setup — CLI Reference

Owner: Mercylin — Service B (ECR, task definition, security group, ECS service, pipeline).

See `docs/aws/phase1-planning.md` for the full dependency graph, failure predictions, and traffic
contracts this setup implements. See `docs/aws/service-a-and-platform-setup.md` for the platform
resources this depends on (cluster, Service Connect namespace, ALB) — those are created once by the
platform/service-a owner and are **not** recreated here.

Service B is not registered with the ALB or a target group. Per the traffic contract
(`Internet → ALB → A → B → C`), the only path into service-b is from service-a over Service Connect;
it is never reached directly from the internet.

---

## 0. Shared environment variables

Set these once per shell session before running anything below. Same pattern as the platform/service-a
setup — each team member uses their own named CLI profile, not `default`.

```bash
aws configure --profile devops-g7
# Enter your own IAM user's access key ID + secret access key, region eu-west-2, output format json.
aws sts get-caller-identity --profile devops-g7   # confirms account 827478161993, your IAM user

export AWS_PROFILE=devops-g7
export AWS_DEFAULT_REGION=eu-west-2
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

export VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

export SUBNET_IDS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[].SubnetId' --output text)
SUBNET_ARRAY=($SUBNET_IDS)
export SUBNET_1=${SUBNET_ARRAY[0]}
export SUBNET_2=${SUBNET_ARRAY[1]}

# Needed to authorize service-a -> service-b ingress below; this SG is created by the
# service-a owner (docs/aws/service-a-and-platform-setup.md section 1) and must already exist.
export SVC_A_SG_ID=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values=devops-g7-service-a-sg \
  --query 'SecurityGroups[0].GroupId' --output text)

echo "VPC: $VPC_ID | Subnets: $SUBNET_1 $SUBNET_2 | Account: $ACCOUNT_ID | SVC_A_SG_ID: $SVC_A_SG_ID"
```

---

## 1. Security group (Service B owner)

```bash
SVC_B_SG_ID=$(aws ec2 create-security-group \
  --group-name devops-g7-service-b-sg \
  --description "Service B task SG for devops-g7" \
  --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=devops-mentorship},{Key=Group,Value=group-7},{Key=Owner,Value=service-b-owner},{Key=Environment,Value=lab},{Key=Name,Value=devops-g7-service-b-sg}]' \
  --query 'GroupId' --output text)

# Only service-a may reach service-b, on the app port (3002) — SG reference, not CIDR
aws ec2 authorize-security-group-ingress --group-id $SVC_B_SG_ID \
  --protocol tcp --port 3002 --source-group $SVC_A_SG_ID

echo "SVC_B_SG_ID=$SVC_B_SG_ID"
```

No inbound rule is needed for `service-b → service-c`; that rule lives on `service-c-sg` (see
`docs/aws/service-c-setup.md`) and is authorized from `SVC_B_SG_ID`, so it must be added only after
this security group exists. Outbound is unrestricted by default (AWS security groups are
stateful/allow-all-egress unless explicitly restricted), so no egress rule is required here for the
`service-b → service-c` call.

---

## 2. ECR repository (Service B owner)

```bash
aws ecr create-repository \
  --repository-name devops-g7-service-b \
  --image-tag-mutability IMMUTABLE \
  --tags Key=Project,Value=devops-mentorship Key=Group,Value=group-7 \
         Key=Owner,Value=service-b-owner Key=Environment,Value=lab
```

---

## 3. IAM task role (Service B owner)

The execution role (`devops-g7-ecs-execution-role`) is shared platform infrastructure created once by
the service-a owner — reuse it here rather than recreating it. Only the task role is service-specific.

```bash
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

aws iam create-role \
  --role-name devops-g7-service-b-task-role \
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
  --role-name devops-g7-service-b-task-role \
  --policy-name devops-g7-ecs-exec-policy \
  --policy-document file:///tmp/ecs-exec-policy.json
```

---

## 4. Build and push the first image (manual, before the pipeline exists)

```bash
aws ecr get-login-password --region $AWS_DEFAULT_REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com

COMMIT_SHA=$(git rev-parse --short=7 HEAD)
IMAGE_URI=$ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/devops-g7-service-b:$COMMIT_SHA

docker build -t $IMAGE_URI -f services/service-b/Dockerfile .
docker push $IMAGE_URI

echo "IMAGE_URI=$IMAGE_URI"
```

**CPU/memory justification:** 256 CPU units (.25 vCPU) / 512 MB — same reasoning as service-a.
Service B is a single-threaded-per-request Flask dev server doing lightweight I/O (forwarding to
service-c) with no CPU-bound work, at lab-scale traffic. Revisit under `scripts/load-test.sh` load if
p95 latency or OOM-kills show up in CloudWatch.

## 5. Register the task definition

```bash
sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" -e "s|<COMMIT_SHA>|$COMMIT_SHA|g" \
  ecs/service-b-task-definition.json > /tmp/service-b-task-definition.rendered.json

aws ecs register-task-definition --cli-input-json file:///tmp/service-b-task-definition.rendered.json
```

---

## 6. ECS service for Service B (Service Connect only — no load balancer)

```bash
aws ecs create-service \
  --cluster devops-g7-cluster \
  --service-name devops-g7-service-b-svc \
  --task-definition devops-g7-service-b-task \
  --desired-count 1 \
  --launch-type FARGATE \
  --platform-version LATEST \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$SVC_B_SG_ID],assignPublicIp=ENABLED}" \
  --service-connect-configuration '{
    "enabled": true,
    "namespace": "g7.internal",
    "services": [{
      "portName": "service-b",
      "discoveryName": "service-b",
      "clientAliases": [{ "port": 3002, "dnsName": "service-b" }]
    }]
  }' \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --enable-execute-command \
  --tags key=Project,value=devops-mentorship key=Group,value=group-7 \
         key=Owner,value=service-b-owner key=Environment,value=lab
```

---

## 7. Verify

Service B has no public endpoint, so verify it from inside the mesh (ECS Exec into service-a) and via
the full end-to-end path through the ALB.

```bash
# Task state
aws ecs describe-services --cluster devops-g7-cluster --services devops-g7-service-b-svc \
  --query 'services[0].{status:status,running:runningCount,desired:desiredCount}'

# From inside service-a's task, Service Connect DNS resolves service-b:3002
TASK_ARN=$(aws ecs list-tasks --cluster devops-g7-cluster --service-name devops-g7-service-a-svc \
  --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster devops-g7-cluster --task $TASK_ARN \
  --container service-a --interactive \
  --command "python3 -c \"import urllib.request; print(urllib.request.urlopen('http://service-b:3002/health').read())\""

# End-to-end through the ALB once service-c also exists:
curl -i http://<alb-dns>/greet-service-b
```

Until `devops-g7-service-c-svc` also exists, expect service-b's own `/health` to report
`"dependencies": {"service-c": "unreachable"}` — that's expected and proves service-b's networking,
health check, and Service Connect registration are correct in isolation.

---

## Still outstanding for Service B's part specifically

- The `service-b → service-c` SG rule (needs `devops-g7-service-c-sg` to exist first — see
  `docs/aws/service-c-setup.md`)
- CodePipeline + CodeBuild project for Service B (source → build → ECR push → ECS deploy), using
  `buildspecs/service-b.yml`, so merges to `main` deploy automatically instead of the manual
  build/push/register done above
- Gate 2 negative tests (`Internet → service-b:3002` denied, `A → C` denied, `C → B` denied) once all
  three services and their SGs exist
