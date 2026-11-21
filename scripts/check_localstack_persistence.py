"""Ensaia os dois S3 do Compose em projeto/volumes descartáveis e portas aleatórias."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("s3", "s3-backup")


def compose_config() -> dict:
    result = subprocess.run(
        ["docker", "compose", "--profile", "backup", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    configured = json.loads(result.stdout)
    services, volumes = {}, {}
    for role in ROLES:
        original = configured["services"][role]
        environment = dict(original["environment"])
        if str(environment.get("PERSIST_S3")) != "1":
            raise AssertionError(f"{role}: persistência não habilitada no Compose")
        # Nunca reutilizar credenciais, portas ou volumes nomeados do ambiente real.
        environment.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test")
        mounts = []
        for mount in original["volumes"]:
            if mount["type"] == "volume":
                assert not configured["volumes"][mount["source"]].get("external")
                volumes[mount["source"]] = {}
                mounts.append(
                    {"type": "volume", "source": mount["source"], "target": mount["target"]}
                )
        assert any(mount["target"] == "/persisted-data" for mount in mounts)
        services[role] = {
            "image": original["image"],
            "environment": environment,
            "healthcheck": original["healthcheck"],
            "volumes": mounts,
            "ports": [{"target": 4566, "host_ip": "127.0.0.1"}],
        }
    return {"services": services, "volumes": volumes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-only", action="store_true", help="Validar sem daemon Docker")
    args = parser.parse_args()
    config = compose_config()
    if args.config_only:
        print("s3 e s3-backup: persistência habilitada; configuração isolada do ambiente real")
        return
    project = "check-persistence-" + uuid4().hex
    with TemporaryDirectory(prefix="check-persistence-") as directory:
        path = Path(directory) / "compose.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        command = ["docker", "compose", "--project-name", project, "--file", str(path)]

        def run(*arguments: str) -> str:
            result = subprocess.run([*command, *arguments], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return result.stdout.strip()

        def client(role: str):
            address = run("port", role, "4566")
            return boto3.client(
                "s3",
                endpoint_url=f"http://{address}",
                region_name="us-east-1",
                aws_access_key_id="test",
                aws_secret_access_key="test",
                config=Config(
                    connect_timeout=3,
                    read_timeout=10,
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )

        bucket = "persistence-" + uuid4().hex
        versions = {}
        try:
            run("up", "--detach", "--wait", "--wait-timeout", "180")
            for role in ROLES:
                s3 = client(role)
                s3.create_bucket(Bucket=bucket)
                s3.put_bucket_versioning(
                    Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
                )
                versions[role] = []
                for revision in (1, 2):
                    body = f"synthetic {role} revision {revision}".encode()
                    response = s3.put_object(Bucket=bucket, Key="probe", Body=body)
                    assert response.get("VersionId") not in (None, "null")
                    versions[role].append((response["VersionId"], hashlib.sha256(body).hexdigest()))
            # Recriar containers, mantendo APENAS os volumes exclusivos deste ensaio.
            run("down")
            run("up", "--detach", "--wait", "--wait-timeout", "180")
            for role in ROLES:
                s3 = client(role)
                listed = s3.list_object_versions(Bucket=bucket)["Versions"]
                assert {item["VersionId"] for item in listed} == {
                    version for version, _ in versions[role]
                }
                for version, checksum in versions[role]:
                    result = s3.get_object(Bucket=bucket, Key="probe", VersionId=version)
                    with result["Body"] as body:
                        assert hashlib.sha256(body.read()).hexdigest() == checksum
                assert (
                    s3.head_object(Bucket=bucket, Key="probe")["VersionId"] == versions[role][-1][0]
                )
                print(f"{role}: duas versões, hashes e versão atual preservados após recriação")
        except BaseException:
            print(run("logs", "--no-color"))
            raise
        finally:
            # O nome aleatório e o arquivo gerado não contêm volumes externos ou nomes físicos.
            run("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
