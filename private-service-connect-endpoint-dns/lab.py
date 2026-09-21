#!/usr/bin/env python3
"""Build and remove an isolated PSC lab. Plan is offline; preflight is read-only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent
REGION = "asia-northeast1"
ZONE = REGION + "-b"


def utc():
    return datetime.now(timezone.utc).isoformat()


def build_plan(producer, consumer, prefix, private):
    """Each action has its exact inverse. No wildcard deletions or IAM changes."""
    actions = []
    regional, zonal = ["--region=" + REGION], ["--zone=" + ZONE]
    name = lambda suffix: prefix + "-" + suffix

    def resource(project, collection, suffix, scope, flags):
        n = name(suffix)
        actions.append({"project": project, "name": n, "kind": collection,
                        "create": collection + ["create", n] + scope + flags,
                        "delete": collection + ["delete", n] + scope})

    for side, project, cidr, ip in [("p", producer, "10.10.0.0/24", "10.10.0.2"),
                                    ("c", consumer, "10.20.0.0/24", "10.20.0.2")]:
        resource(project, ["compute", "networks"], side + "-net", [], ["--subnet-mode=custom"])
        resource(project, ["compute", "networks", "subnets"], side + "-subnet", regional,
                 ["--network=" + name(side + "-net"), "--range=" + cidr])
        resource(project, ["compute", "firewall-rules"], side + "-iap", [],
                 ["--network=" + name(side + "-net"), "--allow=tcp:22",
                  "--source-ranges=35.235.240.0/20", "--target-tags=" + name(side)])
        resource(project, ["compute", "instances"], side + "-vm", zonal,
                 ["--machine-type=e2-micro", "--subnet=" + name(side + "-subnet"),
                  "--private-network-ip=" + ip, "--image-family=debian-12",
                  "--image-project=debian-cloud", "--boot-disk-size=10GB",
                  "--no-service-account", "--no-scopes", "--tags=" + name(side),
                  "--metadata=block-project-ssh-keys=TRUE,enable-oslogin=FALSE",
                  "--metadata-from-file=startup-script=" + str(ROOT / "startup.sh")
                  + ",ssh-keys=" + str(private / "ssh-metadata"),
                  "--labels=purpose=psc-blog-lab"])
    resource(producer, ["compute", "networks", "subnets"], "nat", regional,
             ["--network=" + name("p-net"), "--range=10.10.10.0/24", "--purpose=PRIVATE_SERVICE_CONNECT"])
    for suffix, sources in [("health", "35.191.0.0/16,130.211.0.0/22"), ("nat-http", "10.10.10.0/24")]:
        resource(producer, ["compute", "firewall-rules"], suffix, [],
                 ["--network=" + name("p-net"), "--allow=tcp:80", "--source-ranges=" + sources,
                  "--target-tags=" + name("p")])
    resource(producer, ["compute", "instance-groups", "unmanaged"], "group", zonal, [])
    actions.append({"project": producer, "name": name("group"), "kind": [],
                    "create": ["compute", "instance-groups", "unmanaged", "add-instances", name("group"),
                               "--instances=" + name("p-vm"), *zonal], "delete": None})
    resource(producer, ["compute", "health-checks"], "health", regional, ["--port=80"])
    # gcloud health-checks uses 'create tcp NAME', unlike most collections.
    actions[-1]["create"] = ["compute", "health-checks", "create", "tcp", name("health"), *regional, "--port=80"]
    resource(producer, ["compute", "backend-services"], "backend", regional,
             ["--load-balancing-scheme=INTERNAL", "--protocol=TCP", "--network=" + name("p-net"),
              "--health-checks=" + name("health"), "--health-checks-region=" + REGION])
    actions.append({"project": producer, "name": name("backend"), "kind": [],
                    "create": ["compute", "backend-services", "add-backend", name("backend"), *regional,
                               "--instance-group=" + name("group"), "--instance-group-zone=" + ZONE], "delete": None})
    resource(producer, ["compute", "addresses"], "ilb-ip", regional,
             ["--subnet=" + name("p-subnet"), "--addresses=10.10.0.10"])
    resource(producer, ["compute", "forwarding-rules"], "ilb", regional,
             ["--load-balancing-scheme=INTERNAL", "--network=" + name("p-net"),
              "--subnet=" + name("p-subnet"), "--address=" + name("ilb-ip"), "--ports=80",
              "--ip-protocol=TCP", "--backend-service=" + name("backend"), "--backend-service-region=" + REGION])
    resource(producer, ["compute", "service-attachments"], "service", regional,
             ["--target-service=projects/" + producer + "/regions/" + REGION + "/forwardingRules/" + name("ilb"),
              "--connection-preference=ACCEPT_MANUAL", "--nat-subnets=" + name("nat"), "--reconcile-connections"])
    resource(consumer, ["service-directory", "namespaces"], "namespace", ["--location=" + REGION], [])
    resource(consumer, ["compute", "addresses"], "endpoint-ip", regional,
             ["--subnet=" + name("c-subnet"), "--addresses=10.20.0.10"])
    resource(consumer, ["compute", "forwarding-rules"], "endpoint", regional,
             ["--network=" + name("c-net"), "--address=" + name("endpoint-ip"),
              "--target-service-attachment=projects/" + producer + "/regions/" + REGION + "/serviceAttachments/" + name("service"),
              "--service-directory-registration=projects/" + consumer + "/locations/" + REGION + "/namespaces/" + name("namespace")])
    resource(consumer, ["dns", "managed-zones"], "dns", [],
             ["--description=Temporary PSC lab", "--dns-name=psc.test.", "--visibility=private", "--networks=" + name("c-net")])
    return actions


class Lab:
    def __init__(self, args):
        self.args = args
        self.private = ROOT / ".private" / args.prefix
        self.manifest = self.private / "manifest.json"
        self.actions = build_plan(args.producer_project, args.consumer_project, args.prefix, self.private)

    def call(self, project, *cmd, check=True, timeout=300):
        result = subprocess.run(["gcloud", "--quiet", "--project=" + project, *cmd],
                                capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            self.private.mkdir(parents=True, mode=0o700, exist_ok=True)
            error = self.private / "last-error.txt"
            error.write_text(result.stderr)
            error.chmod(0o600)
            raise RuntimeError("gcloud failed; inspect .private/PREFIX/last-error.txt")
        return result

    def read(self, project, *cmd):
        return json.loads(self.call(project, *cmd, "--format=json").stdout)

    def preflight(self):
        required = {}
        for project, apis in [(self.args.producer_project, {"compute.googleapis.com", "iap.googleapis.com"}),
                              (self.args.consumer_project, {"compute.googleapis.com", "iap.googleapis.com",
                                                            "servicedirectory.googleapis.com", "dns.googleapis.com"})]:
            required.setdefault(project, set()).update(apis)
        for project, apis in required.items():
            enabled = {x["config"]["name"] for x in self.read(project, "services", "list", "--enabled")}
            missing = sorted(apis - enabled)
            if missing:
                raise RuntimeError("Required APIs not enabled: " + ", ".join(missing))
        collections = {(a["project"], tuple(a["kind"])) for a in self.actions if a["kind"]}
        collections.update((project, ("compute", "disks")) for project in required)
        for project, kind in sorted(collections):
            scope = ["--location=" + REGION] if kind[0] == "service-directory" else []
            rows = self.read(project, *kind, "list", *scope)
            if any(x.get("name", "").split("/")[-1].startswith(self.args.prefix) for x in rows):
                raise RuntimeError("Existing prefix in " + " ".join(kind))
        print("Preflight passed: APIs accessible; no resource prefix collisions.", flush=True)

    def save(self):
        self.manifest.write_text(json.dumps(self.state, indent=2) + "\n")
        self.manifest.chmod(0o600)

    def load(self):
        self.state = json.loads(self.manifest.read_text())
        expected = (self.args.producer_project, self.args.consumer_project, self.args.prefix)
        actual = tuple(self.state[k] for k in ["producer_project", "consumer_project", "prefix"])
        if actual != expected:
            raise RuntimeError("Arguments do not match the creation manifest")

    def create(self):
        if self.manifest.exists():
            raise RuntimeError("Manifest exists; use cleanup, then choose a new prefix")
        self.preflight()
        self.private.mkdir(parents=True, mode=0o700, exist_ok=True)
        key = self.private / "ssh-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "psc-lab", "-f", str(key)], check=True)
        (self.private / "ssh-metadata").write_text("psclab:" + key.with_suffix(".pub").read_text())
        self.state = {"producer_project": self.args.producer_project, "consumer_project": self.args.consumer_project,
                      "prefix": self.args.prefix, "started_utc": utc(), "resources": [], "complete": False}
        self.save()
        for action in self.actions:
            if action["kind"] == ["compute", "instances"]:
                # Track the implicit boot disk before the VM attempt; partial VM creation can leave it behind.
                self.state["resources"].append({"project": action["project"], "name": action["name"],
                    "kind": ["compute", "disks"], "delete": ["compute", "disks", "delete", action["name"], "--zone=" + ZONE],
                    "status": "implicit-boot-disk"})
                self.save()
            if action["delete"]:
                item = dict(action, status="attempted")
                self.state["resources"].append(item)
                self.save()  # A timeout can occur after creation succeeds.
            self.call(action["project"], *action["create"])
            if action["delete"]:
                item["status"] = "created"
                self.save()
            print("Configured " + action["name"], flush=True)
        self.state["complete"] = True
        self.save()

    def ssh(self, side, command, *, check=True):
        project = self.args.producer_project if side == "p" else self.args.consumer_project
        return self.call(project, "compute", "ssh", "psclab@" + self.args.prefix + "-" + side + "-vm",
                         "--zone=" + ZONE, "--tunnel-through-iap",
                         "--ssh-key-file=" + str(self.private / "ssh-key"),
                         "--ssh-flag=-oBatchMode=yes", "--ssh-flag=-oConnectTimeout=10",
                         "--ssh-flag=-oStrictHostKeyChecking=accept-new",
                         "--ssh-flag=-oUserKnownHostsFile=" + str(self.private / "known_hosts"),
                         "--command=" + command, check=check, timeout=120)

    def status(self):
        endpoint = self.read(self.args.consumer_project, "compute", "forwarding-rules", "describe",
                             self.args.prefix + "-endpoint", "--region=" + REGION)
        health = self.read(self.args.producer_project, "compute", "backend-services", "get-health",
                           self.args.prefix + "-backend", "--region=" + REGION)
        states = [x.get("healthState") for group in health for x in group.get("status", {}).get("healthStatus", [])]
        firewall = self.read(self.args.producer_project, "compute", "firewall-rules", "describe", self.args.prefix + "-nat-http")
        return {"utc": utc(), "psc_status": endpoint.get("pscConnectionStatus"),
                "endpoint_ip": endpoint.get("IPAddress"), "backend_health": states,
                "nat_http_rule_disabled": firewall.get("disabled", False)}

    def dns(self, present):
        cmd = ["dns", "record-sets", "create" if present else "delete", "hello.psc.test.",
               "--zone=" + self.args.prefix + "-dns", "--type=A"]
        if present:
            cmd += ["--ttl=30", "--rrdatas=10.20.0.10"]
        self.call(self.args.consumer_project, *cmd)

    def firewall(self, disabled):
        self.call(self.args.producer_project, "compute", "firewall-rules", "update", self.args.prefix + "-nat-http",
                  "--disabled" if disabled else "--no-disabled")

    def cleanup(self):
        self.load()
        # DNS A record belongs only to the dedicated lab zone.
        zone = self.args.prefix + "-dns"
        zones = self.read(self.args.consumer_project, "dns", "managed-zones", "list")
        if any(z["name"] == zone for z in zones):
            records = self.read(self.args.consumer_project, "dns", "record-sets", "list", "--zone=" + zone)
            if any(x["name"] == "hello.psc.test." and x["type"] == "A" for x in records):
                self.dns(False)
        # Auto DNS zones may be named by Google rather than the lab prefix.
        namespace_suffix = "/locations/" + REGION + "/namespaces/" + self.args.prefix + "-namespace"
        for z in zones:
            ns = z.get("serviceDirectoryConfig", {}).get("namespace", {}).get("namespaceUrl", "")
            if ns.endswith(namespace_suffix):
                delete = ["dns", "managed-zones", "delete", z["name"]]
                if not any(x["delete"] == delete for x in self.state["resources"]):
                    namespace_index = next(i for i, x in enumerate(self.state["resources"])
                                           if x["kind"] == ["service-directory", "namespaces"])
                    self.state["resources"].insert(namespace_index + 1,
                        {"project": self.args.consumer_project, "name": z["name"],
                         "kind": ["dns", "managed-zones"], "delete": delete, "status": "auto-created"})
                    self.save()
        failures = []
        for item in list(reversed(self.state["resources"])):
            kind = item["kind"]
            scope = ["--location=" + REGION] if kind[0] == "service-directory" else []
            rows = self.read(item["project"], *kind, "list", *scope)
            if any(x.get("name", "").split("/")[-1] == item["name"] for x in rows):
                if kind[0] == "service-directory":
                    services = self.read(item["project"], "service-directory", "services", "list",
                                         "--namespace=" + item["name"], "--location=" + REGION)
                    if services:
                        failures.append(item["name"])
                        print("Namespace is not empty; retained " + item["name"], flush=True)
                        continue
                result = self.call(item["project"], *item["delete"], check=False)
                if result.returncode:
                    (self.private / "cleanup-error.txt").write_text(result.stderr)
                    failures.append(item["name"])
                    continue
            self.state["resources"].remove(item)
            self.save()
            print("Removed " + item["name"], flush=True)
        self.state["cleanup_utc"] = utc()
        self.state["cleanup_failures"] = failures
        self.save()
        if failures:
            raise RuntimeError("Cleanup incomplete; inspect manifest and retry cleanup")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["plan", "preflight", "create", "status", "cleanup"])
    p.add_argument("--producer-project", required=True)
    p.add_argument("--consumer-project", required=True)
    p.add_argument("--prefix", default="psc-lab-0921")
    args = p.parse_args()
    if not re.fullmatch(r"psc-lab-[a-z0-9-]{1,24}", args.prefix):
        p.error("prefix must begin with psc-lab- and use lowercase letters, digits or hyphens")
    for project in [args.producer_project, args.consumer_project]:
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
            p.error("invalid project ID")
    return args


def main():
    os.umask(0o077)
    args = parse_args()
    lab = Lab(args)
    if args.action == "plan":
        for action in lab.actions:
            print(shlex.join(["gcloud", "--quiet", "--project=" + action["project"], *action["create"]]))
    elif args.action == "status":
        lab.load()
        print(json.dumps(lab.status(), indent=2))
    else:
        getattr(lab, args.action)()


if __name__ == "__main__":
    main()
