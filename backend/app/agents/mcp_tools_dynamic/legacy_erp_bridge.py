import asyncio


import httpx

import logging

from app.core.outbound import guarded_async_client, assert_safe_outbound_url


class LegacyErpBridgeTool:

    def __init__(self, base_url: str):

        self.base_url = base_url

        # Configure logger for this tool class here if needed.


    async def execute(self, payload: dict) -> None:

        try:

            # base_url is caller/tenant-supplied — vet it up front and route
            # through the SSRF-guarded client so it cannot reach cloud-metadata
            # or private hosts (it re-vets the resolved IP at connect time).
            url = f"{self.base_url}/api/legacy_erp_bridge"
            assert_safe_outbound_url(url)
            async with guarded_async_client(timeout=30) as client:
                response = await client.post(url, json=payload)

            response.raise_for_status()

            logging.info("Payload successfully processed by legacy ERP bridge.")

        except httpx.HTTPStatusError as exc:

            if exc.response.status_code == 400:

                error_message = f"Bad Request: {exc}"

            elif exc.response.status_code == 401:

                error_message = "Unauthorized access to the Legacy ERP Bridge."

            else:

                error_message = str(exc)

            logging.error(error_message)


# Example usage (would normally be in a separate script or part of an incident management system):

async def main():

    tool_instance = LegacyErpBridgeTool(base_url="http://legacy-erp.example.com")

    payload_data = {"key": "value"}

    await tool_instance.execute(payload=payload_data)

if __name__ == "__main__":

    asyncio.run(main())