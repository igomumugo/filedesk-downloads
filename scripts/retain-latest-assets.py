"""Keep installers on the verified current public FileDesk release and preserve release notes."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

REPOSITORY = "igomumugo/filedesk-downloads"
API = f"repos/{REPOSITORY}"
INSTALLERS = ("FileDesk-macOS-AppleSilicon.dmg", "FileDesk-macOS-Intel.dmg")


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", f"{API}/{path}"]))


def list_all(path):
    groups = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp", f"{API}/{path}?per_page=100"
    ]))
    return [item for group in groups for item in group]


def version(tag):
    if not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)+", tag):
        return None
    return tuple(int(part) for part in tag[1:].split("."))


def verify_installers(release):
    assets = {asset["name"]: asset for asset in list_all(f"releases/{release['id']}/assets")}
    expected = {part for name in INSTALLERS for part in (name, name + ".sha256")}
    if not expected.issubset(assets):
        raise ValueError("The latest release is missing an installer or checksum.")
    with tempfile.TemporaryDirectory() as folder:
        command = ["gh", "release", "download", release["tag_name"], "--repo", REPOSITORY, "--dir", folder]
        for name in sorted(expected):
            command.extend(["--pattern", name])
        subprocess.run(command, check=True)
        for name in INSTALLERS:
            checksum = (Path(folder) / (name + ".sha256")).read_text().strip()
            with (Path(folder) / name).open("rb") as stream:
                hasher = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(block)
                digest = hasher.hexdigest()
            if checksum.split() != [digest, name] or assets[name].get("digest") != "sha256:" + digest:
                raise ValueError(f"Checksum mismatch for {name}.")
            if assets[name]["size"] <= 0 or (Path(folder) / name).stat().st_size != assets[name]["size"]:
                raise ValueError(f"Incomplete installer: {name}.")


def main():
    current = api("releases/latest")
    current_version = version(current["tag_name"])
    if current_version is None or current["draft"] or current["prerelease"]:
        raise ValueError("A published stable FileDesk version is required.")
    verify_installers(current)
    removed = 0
    for release in list_all("releases"):
        prior = version(release["tag_name"])
        if release["draft"] or prior is None or prior >= current_version or release["id"] == current["id"]:
            continue
        for asset in list_all(f"releases/{release['id']}/assets"):
            if api("releases/latest")["id"] != current["id"]:
                raise RuntimeError("The latest release changed. Rerun against the new release.")
            subprocess.run(["gh", "api", "--method", "DELETE", f"{API}/releases/assets/{asset['id']}"], check=True)
            print(f"Removed {release['tag_name']} attachment {asset['name']}", flush=True)
            removed += 1
    print(f"Verified both installers for {current['tag_name']}. Removed {removed} earlier attachments.")


if __name__ == "__main__":
    main()
