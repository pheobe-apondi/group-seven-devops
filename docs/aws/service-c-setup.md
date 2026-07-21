# Service C Setup — CLI Reference

Owner: Mercylin — Service C (ECR, task definition, security group, ECS service, pipeline).

See `docs/aws/phase1-planning.md` for the full dependency graph, failure predictions, and traffic
contracts this setup implements. See `docs/aws/service-a-and-platform-setup.md` for the platform
resources this depends on (cluster, Service Connect namespace, ALB) — those are created once by the
platform/service-a owner and are **not** recreated here.

Service C is not registered with the ALB or a target group. Per the traffic contract
(`Internet → ALB → A → B → C`), the only inbound path to service-c is from service-b over Service
Connect. Service C also makes one outbound call of its own: the `/greeting-rcvd` callback to
service-a on port 3001 (`service_c.py`'s `/greet-c` handler) — this is the reverse of the main flow
and easy to miss when wiring up security groups.

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

# Needed to authorize service-b -> service-c ingress below; devops-g7-service-b-sg is created in
# docs/aws/service-b-setup.md and must already exist.
export SVC_B_SG_ID=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values=devops-g7-service-b-sg \
  --query 'SecurityGroups[0].GroupId' --output text)

echo "VPC: $VPC_ID | Subnets: $SUBNET_1 $SUBNET_2 | Account: $ACCOUNT_ID | SVC_B_SG_ID: $SVC_B_SG_ID"
```

---

## 1. Security group (Service C owner)

```bash
SVC_C_SG_ID=$(aws ec2 create-security-group \
  --group-name devops-g7-service-c-sg \
  --description "Service C task SG for devops-g7" \
  --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=devops-mentorship},{Key=Group,Value=group-7},{Key=Owner,Value=service-c-owner},{Key=Environment,Value=lab},{Key=Name,Value=devops-g7-service-c-sg}]' \
  --query 'GroupId' --output text)

# Only service-b may reach service-c, on the app port (3003) — SG reference, not CIDR
aws ec2 authorize-security-group-ingress --group-id $SVC_C_SG_ID \
  --protocol tcp --port 3003 --source-group $SVC_B_SG_ID

echo "SVC_C_SG_ID=$SVC_C_SG_ID"
```

Outbound is unrestricted by default (AWS security groups are stateful/allow-all-egress unless
explicitly restricted), so no egress rule is needed here for the `service-c → service-a` callback.
That callback still requires **service-a's** security group to accept inbound from `SVC_C_SG_ID` on
port 3001 — that rule lives on `devops-g7-service-a-sg`, which this doc does not own. It's already
called out as a commented, not-yet-applied line in
`docs/aws/service-a-and-platform-setup.md` (section 1):

```bash
# aws ec2 authorize-security-group-ingress --group-id $SVC_A_SG_ID \
#   --protocol tcp --port 3001 --source-group $SVC_C_SG_ID
```

Once `SVC_C_SG_ID` above is created, send its value to the service-a owner (or whoever runs that
doc) so they can uncomment and run that line. Without it, every request that reaches service-c will
504 on the callback wait even though `A → B → C` succeeds — this is the exact edge called out in
`docs/aws/phase1-planning.md`'s failure predictions.

---

## 2. ECR repository (Service C owner)

```bash
aws ecr create-repository \
  --repository-name devops-g7-service-c \
  --image-tag-mutability IMMUTABLE \
  --tags Key=Project,Value=devops-mentorship Key=Group,Value=group-7 \
         Key=Owner,Value=service-c-owner Key=Environment,Value=lab
```

---

## 3. IAM task role (Service C owner)

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
  --role-name devops-g7-service-c-task-role \
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
  --role-name devops-g7-service-c-task-role \
  --policy-name devops-g7-ecs-exec-policy \
  --policy-document file:///tmp/ecs-exec-policy.json
```

---

## 4. Build and push the first image (manual, before the pipeline exists)

```bash
aws ecr get-login-password --region $AWS_DEFAULT_REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com

COMMIT_SHA=$(git rev-parse --short=7 HEAD)
IMAGE_URI=$ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/devops-g7-service-c:$COMMIT_SHA

docker build -t $IMAGE_URI -f services/service-c/Dockerfile .
docker push $IMAGE_URI

echo "IMAGE_URI=$IMAGE_URI"
```

**CPU/memory justification:** 256 CPU units (.25 vCPU) / 512 MB — same reasoning as service-a and
service-b. Service C is the leaf of the call chain: it handles one inbound request and fires one
outbound callback, no CPU-bound work, at lab-scale traffic. Revisit under `scripts/load-test.sh` load
if p95 latency or OOM-kills show up in CloudWatch.

## 5. Register the task definition

```bash
sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" -e "s|<COMMIT_SHA>|$COMMIT_SHA|g" \
  ecs/service-c-task-definition.json > /tmp/service-c-task-definition.rendered.json

aws ecs register-task-definition --cli-input-json file:///tmp/service-c-task-definition.rendered.json
```

---

## 6. ECS service for Service C (Service Connect only — no load balancer)

```bash
aws ecs create-service \
  --cluster devops-g7-cluster \
  --service-name devops-g7-service-c-svc \
  --task-definition devops-g7-service-c-task \
  --desired-count 1 \
  --launch-type FARGATE \
  --platform-version LATEST \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$SVC_C_SG_ID],assignPublicIp=ENABLED}" \
  --service-connect-configuration '{
    "enabled": true,
    "namespace": "g7.internal",
    "services": [{
      "portName": "service-c",
      "discoveryName": "service-c",
      "clientAliases": [{ "port": 3003, "dnsName": "service-c" }]
    }]
  }' \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --enable-execute-command \
  --tags key=Project,value=devops-mentorship key=Group,value=group-7 \
         key=Owner,value=service-c-owner key=Environment,value=lab
```

---

## 7. Verify

Service C has no public endpoint, so verify it from inside the mesh (ECS Exec into service-b) and via
the full end-to-end path through the ALB.

```bash
# Task state
aws ecs describe-services --cluster devops-g7-cluster --services devops-g7-service-c-svc \
  --query 'services[0].{status:status,running:runningCount,desired:desiredCount}'

# From inside service-b's task, Service Connect DNS resolves service-c:3003
TASK_ARN=$(aws ecs list-tasks --cluster devops-g7-cluster --service-name devops-g7-service-b-svc \
  --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster devops-g7-cluster --task $TASK_ARN \
  --container service-b --interactive \
  --command "python3 -c \"import urllib.request; print(urllib.request.urlopen('http://service-c:3003/health').read())\""

# Full A -> B -> C -> callback loop through the ALB, once the service-a-sg rule above is applied:
curl -i http://<alb-dns>/greet-service-b
```

A healthy `service-c` alone shows up as `service-b`'s `/health` reporting
`"dependencies": {"service-c": "ok"}`. The full loop (`/greet-service-b` returning
`{"status": "forwarded", ...}` without a `504`) additionally requires the
`service-c → service-a` SG rule from section 1 to be applied on `devops-g7-service-a-sg`.

---

## Still outstanding for Service C's part specifically

- Confirming the service-a owner has applied the `service-c → service-a:3001` ingress rule on
  `devops-g7-service-a-sg` (section 1) — without it every request 504s on the callback wait
- CodePipeline + CodeBuild project for Service C (source → build → ECR push → ECS deploy), using
  `buildspecs/service-c.yml`, so merges to `main` deploy automatically instead of the manual
  build/push/register done above
- Gate 2 negative tests (`Internet → service-c:3003` denied, `A → C` denied, `service-c → anything
  other than service-a:3001` denied) once all three services and their SGs exist
