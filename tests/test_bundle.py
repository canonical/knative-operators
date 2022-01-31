import json

import aiohttp
import pytest
from pytest_operator.plugin import OpsTest


async def wait(ops_test):
    await ops_test.model.wait_for_idle(timeout=60 * 10)
    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=available",
        "deployment",
        "--all",
        "--all-namespaces",
        "--timeout=5m",
        check=True,
    )

    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "pod",
        "--all",
        "-A",
        "--timeout=5m",
        check=True,
    )


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build and deploy the charm."""

    print("Setting up permissions")

    await ops_test.run("kubectl", "apply", "-f", "crb.yaml", check=True)

    print("Deploying Kourier")

    await ops_test.run("kubectl", "apply", "-f", "tests/kourier.yaml", check=True)

    print("Deploying bundle")

    await ops_test.deploy_bundle(serial=True, extra_args=["--trust"])

    await wait(ops_test)

    print("Bundle deployed, deploying helloworld-go example app")

    await ops_test.run("kubectl", "apply", "-f", "examples/helloworld-go.yaml", check=True)

    await wait(ops_test)

    print("Example app deployed, ensuring connectivity")

    gateway_json = await ops_test.run(
        "kubectl",
        "get",
        "ksvc/helloworld-go",
        "-ojson",
        check=True,
    )

    ksvc_obj = json.loads(gateway_json[1])
    ksvc_url = ksvc_obj["status"]["url"]
    async with aiohttp.ClientSession(raise_for_status=True) as client:
        results = await client.get(ksvc_url)
        text = await results.text()

        assert text == "Hello Go Sample v1!\n"
