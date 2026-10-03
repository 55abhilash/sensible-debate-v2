# Deploying Sensible Debate to AWS, with real autoscaling

This is a different deployment target from `DEPLOYMENT.md` (a single
Ubuntu VPS). That one is simpler and cheaper if you never expect more
than one server's worth of traffic. This one is for the "this might
actually take off" case: it runs on more than one server, adds and
removes servers automatically as traffic rises and falls, and survives
losing any single server without anyone's debate breaking.

**Read this first, because it's the one thing worth actually
understanding rather than just copy-pasting:** the original build kept
each debate's live state - whose turn it is, the timers, the transcript
so far - in the memory of a single Python process. That's exactly right
for one server. It silently breaks the moment there's more than one,
because the two people in a debate can easily end up connected to two
*different* servers that have no way to see each other's memory. So
"add a load balancer" on its own would not have given you working
autoscaling - it would have given you a coin-flip chance of debates
hanging forever the moment traffic actually required a second instance.

What actually makes this correct is in `app/realtime.py`,
`app/debate_room.py` and `app/matchmaking.py`: live state now lives in
Redis, shared by every server, with a small amount of careful
coordination (a distributed lock for "both people just connected,
start the clock", and an atomic claim so a 5-minute timer fires exactly
once no matter how many servers are watching for it). I tested this
directly - two separate server processes, each holding one participant's
connection, deliberately split across them - before writing any of the
infrastructure below. It's not a theoretical fix.

## What you end up with

```
                          ┌─────────────────────┐
  Browser  ── HTTPS ──▶   │   ALB (port 80/443)  │
                          └──────────┬───────────┘
                                     │ HTTP :8000
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
             ┌────────────┐  ┌────────────┐   ┌────────────┐
             │ EC2 (app)  │  │ EC2 (app)  │   │ EC2 (app)  │  ← Auto Scaling
             │  Docker    │  │  Docker    │   │  Docker    │    Group, 1-4
             └─────┬──────┘  └─────┬──────┘   └─────┬──────┘
                    │               │                │
          ┌─────────┴───────────────┴────────────────┴─────────┐
          ▼                                                     ▼
   ┌─────────────┐                                      ┌──────────────┐
   │ ElastiCache │  live debate state, pub/sub           │ RDS Postgres │
   │   Redis     │  ("right now" coordination)           │  (history:   │
   └─────────────┘                                       │   topics,    │
                                                           │  transcripts)│
                                                           └──────────────┘
```

Every app instance is identical and stateless in itself - all of them
can be added or removed at any moment without anyone noticing, because
the two things that matter (live state, permanent history) both live
outside any single instance.

## What this costs

Nothing here scales to zero - there's a fixed monthly floor regardless
of traffic, because a load balancer, a small database, and a small
Redis node all have an always-on cost. What scales with traffic is the
number of EC2 instances behind the load balancer.

| Component | Size | Approx. cost/month |
|---|---|---|
| Application Load Balancer | - | ~$17 (fixed) + a little more under real load |
| EC2 (Auto Scaling Group) | t4g.micro × 1 (baseline) | ~$7 per instance, only while it's running |
| RDS Postgres | db.t4g.micro, 20GB gp3 | ~$15 |
| ElastiCache Redis | cache.t4g.micro, single node | ~$13 |
| CloudWatch Logs | 14-day retention | ~$1-2 |
| ECR, SSM, ACM, data transfer | - | a few cents to a couple of dollars |
| **Baseline total (1 instance, quiet traffic)** | | **~$55-60/month** |

If the Auto Scaling Group adds a second or third instance during a
traffic spike, that's roughly another **$7/month, pro-rated to the
hour** each - a few cents an hour, only while the extra capacity is
actually running. `asg_max_size` (default 4) is your safety cap on how
far that can go without you deciding to raise it.

Two things kept out of this on purpose, both to save money:
- **No NAT Gateway** (~$32+/month saved) - the app instances sit in
  public subnets with public IPs, but a security group only lets the
  load balancer reach them, and RDS/Redis are never internet-reachable
  at all despite being in the same subnets - see `security_groups.tf`.
- **No Multi-AZ RDS, no Redis replica** - a single node of each. Fine
  for an MVP; if either goes down you lose live debate state (recorded
  history in Postgres is safe either way) until AWS auto-recovers the
  instance. Documented as a trade-off, not an oversight - see "Known
  limitations" below.

## Prerequisites

- An AWS account, with the AWS CLI installed and configured (`aws
  configure`) - the same one your Terraform runs will use.
- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.5.
  **I could not run `terraform validate` myself while building this** -
  my sandbox's network access doesn't reach HashiCorp's servers to
  install the Terraform binary. I reviewed every file by hand and
  cross-checked all the moving pieces (variable names, cross-file
  references, the bootstrap script's Terraform-vs-bash escaping) as
  carefully as I could without that step, but you should still run
  `terraform validate` yourself as the very first thing you do, before
  `plan` or `apply`.
- Docker installed locally (to build and push the image). It needs
  buildx support for `--platform linux/arm64` - Docker Desktop and
  recent Docker Engine both have this built in.
- A domain name, if you want HTTPS (strongly recommended before
  posting this anywhere public - see Step 6).

## Step 1: Review the project structure

Everything AWS-specific is under `terraform/`. The app code itself
(`app/`) is the same project as `DEPLOYMENT.md` describes, with three
changes worth knowing about, all covered in more depth in `README.md`:

- `app/realtime.py` is new - the Redis coordination layer.
- `app/debate_room.py` and `app/matchmaking.py` were rewritten to use
  it instead of keeping state in memory.
- `requirements.txt` now includes `redis` and `psycopg[binary]`
  (a Postgres driver) - SQLite is no longer used in production, since a
  local file can't be shared between multiple instances.

## Step 2: terraform init and validate

```bash
cd terraform
terraform init
terraform validate
```

`validate` catches syntax problems before anything touches AWS. If it
finds something, that's the sandbox limitation above showing up - fix
it and keep going; the fixes should be small (a typo, an attribute
name) rather than structural.

Every variable has a working default (see `variables.tf`) - you don't
strictly need a `terraform.tfvars` file to do a first deploy. Copy
`terraform.tfvars.example` to `terraform.tfvars` if you want to change
anything up front (region, instance sizes, `asg_max_size`).

## Step 3: Create the ECR repository (first, on its own)

The Auto Scaling Group's instances need an image to pull the moment
they boot - so the repository has to exist, with an image already
pushed, before you create the instances. Apply just that one resource
first:

```bash
terraform apply -target=aws_ecr_repository.app
```

Note the `ecr_repository_url` it outputs.

## Step 4: Build and push the image

Instances run on Graviton (ARM64) - build for that architecture
specifically:

```bash
cd ..   # back to the project root, where the Dockerfile is

aws ecr get-login-password --region ap-south-1 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.ap-south-1.amazonaws.com

docker buildx build --platform linux/arm64 \
  -t <ecr_repository_url>:latest \
  --push .
```

(Replace the region and `<ecr_repository_url>` with your actual values
from Step 3's output; `<account-id>` is the numeric prefix of that same
URL.)

## Step 5: Apply everything else

```bash
cd terraform
terraform apply
```

This creates the VPC, RDS, ElastiCache, the load balancer, and the
Auto Scaling Group (which will now successfully pull the image you just
pushed). Review the plan before confirming - Terraform will show you
exactly what it's about to create.

Give it a few minutes after `apply` finishes for the first instance to
actually boot, install Docker, and start the app (the target group's
health check has a 180-second grace period for exactly this). Then:

```bash
curl http://$(terraform output -raw alb_dns_name)/healthz
```

`{"ok":true}` means the whole chain - instance, Redis, Postgres - is
actually working, not just that a server answered.

Open the ALB's DNS name (also from `terraform output`) in a browser
and try posting a topic. At this point it's live, just over plain HTTP.

## Step 6: Add HTTPS (do this before posting anywhere public)

This is a two-step process because ACM needs to see a DNS record that
proves you own the domain before it'll issue a certificate, and that
record doesn't exist until Terraform creates the certificate request.

1. Set `domain_name` (a **subdomain**, like `debate.yourdomain.com` -
   not the bare root domain, which most registrars can't point at an
   ALB with a plain CNAME) in `terraform.tfvars`, then:
   ```bash
   terraform apply
   ```
2. Run `terraform output acm_certificate_validation_records`. Add each
   record it shows at your domain's DNS panel (Hostinger, GoDaddy,
   wherever you manage it) - it'll be one CNAME-type record.
3. Also add a CNAME for your actual subdomain (`debate`, or whatever
   you chose) pointing at the `alb_dns_name` output.
4. Wait for both to propagate (usually minutes, occasionally longer),
   then run `terraform apply` again. ACM validates in the background
   once it can see the record - by this second apply it's normally
   already issued, and the HTTPS listener gets created using it.
5. Confirm at `https://debate.yourdomain.com`.

## Verifying it actually scales

Watch the Auto Scaling Group in the EC2 console (or `aws autoscaling
describe-auto-scaling-groups --auto-scaling-group-names
$(terraform output -raw asg_name)`) during any real traffic. The
target-tracking policy in `asg.tf` adds instances when average CPU
crosses ~50% and removes them once it's been comfortably below that for
a while - you don't need to do anything for this to happen. If you want
to see it react to a synthetic spike before trusting it with a real
one, any simple load-testing tool pointed at the ALB's URL will do.

## Deploying a code update

The clean, repeatable way: tag images by version rather than always
`latest`, so changing the tag is what tells Terraform something
changed.

```bash
docker buildx build --platform linux/arm64 -t <ecr_repository_url>:v2 --push .
terraform apply -var="image_tag=v2"
```

Changing `image_tag` changes the launch template, which the
`instance_refresh` block in `asg.tf` picks up automatically - Terraform
triggers a rolling replacement (half the fleet at a time, by default)
so a deploy never drops all instances at once.

The quick-and-dirty alternative, if you just repushed the same `latest`
tag and want existing instances to pick it up without changing any
Terraform variable:
```bash
aws autoscaling start-instance-refresh \
  --auto-scaling-group-name $(terraform output -raw asg_name)
```

## Day-to-day operations

**Logs**, across the whole fleet, in one place:
```bash
aws logs tail $(terraform output -raw log_group_name) --follow
```

**A shell on a running instance**, no SSH keys or bastion needed:
```bash
aws ssm start-session --target <instance-id>
# find instance ids: aws autoscaling describe-auto-scaling-groups \
#   --auto-scaling-group-names $(terraform output -raw asg_name)
```
Once connected, `sudo docker logs -f sensible-debate` shows one
instance's app output directly; `sudo docker exec -it sensible-debate
sh` gets you inside the container.

**Database access.** RDS isn't internet-reachable, by design - connect
via an SSM session's port forwarding, or open a shell there (above) and
use `psql` from inside it if you install it. From your own machine:
```bash
aws ssm start-session --target <instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<db_endpoint-without-port>"],"portNumber":["5432"],"localPortNumber":["5432"]}'
# then, in another terminal:
psql "postgresql://sensible_debate_app@127.0.0.1:5432/sensible_debate"
```
The password is in SSM Parameter Store: `aws ssm get-parameter --name
/sensible-debate/db-password --with-decryption --query
Parameter.Value --output text`.

**Changing the timer durations** (`argument_seconds`,
`reflection_seconds` in `variables.tf`): change the variable, `terraform
apply` - this updates the launch template, which triggers the same
rolling instance refresh as a code deploy.

## Known limitations (in addition to the ones in README.md)

- **Single-AZ RDS and a single Redis node.** No automatic failover if
  either has a problem. For a side project going from zero, this is a
  reasonable trade against the extra ~$15-20/month Multi-AZ/replica
  would add on both - worth revisiting once real usage justifies it.
- **A very small, low-probability race** exists between someone
  clicking "Leave" and a timeout firing for the same debate at almost
  exactly the same instant, documented in code comments in
  `debate_room.py`. The realistic worst case is a debate needing a
  page refresh, not data loss - deliberately not engineered away
  further, since doing so would add real complexity against a
  vanishingly small, low-stakes risk.
- **No WAF, no rate limiting.** If a post genuinely goes viral in an
  adversarial way (not just popular, but targeted abuse), there's
  nothing here yet to blunt it beyond AWS's baseline DDoS protection.
  Worth adding if that becomes a real concern - AWS WAF attached to the
  ALB is the standard next step.
- **This Terraform was not run against real AWS from my end** - see the
  Prerequisites note above. Treat the first `terraform plan` as your
  chance to catch anything before it touches real infrastructure.

## Tearing it down

Everything here costs money while it exists, whether or not anyone's
using it. To stop that:

```bash
cd terraform
terraform destroy
```

This deletes RDS **without a final snapshot** (`skip_final_snapshot =
true`, set for easy iteration during setup) - if there's real debate
history in there you want to keep, take a manual snapshot first:
```bash
aws rds create-db-snapshot \
  --db-instance-identifier sensible-debate-db \
  --db-snapshot-identifier sensible-debate-final-$(date +%F)
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `terraform apply` fails creating the ASG/instances with an image pull error | The image isn't in ECR yet, or the tag doesn't match `image_tag` - redo Step 3/4 before Step 5. |
| Instances launch but never pass the target group health check | Check logs (`aws logs tail ... --follow`) - most likely the app can't reach RDS or Redis (a security group issue) or the DB password fetch from SSM failed (an IAM issue). `aws ssm start-session` in and run `sudo docker logs sensible-debate` directly. |
| `terraform apply` for the ACM certificate step doesn't produce a working HTTPS listener | The DNS validation record hasn't propagated yet, or wasn't added correctly - check `aws acm describe-certificate --certificate-arn <arn>` for its status before re-applying. |
| A debate seems to hang with "Waiting for both of you to connect" | Confirm `/healthz` returns `{"ok":true}` from more than one instance - if Redis itself is unreachable, this is the failure mode (nothing crashes, coordination just can't happen). |
| Costs higher than expected | Check the EC2 console for how many instances the ASG is actually running - if it's pinned at `asg_max_size`, something is either driving real sustained load or the CPU-based scaling target needs tuning (`asg_cpu_target` in `variables.tf`). |
