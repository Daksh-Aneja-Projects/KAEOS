import asyncio


import httpx

import logging


class LegacyErpBridgeTool:

    def __init__(self, base_url: str):

        self.base_url = base_url

        # Configure logger for this tool class here if needed.


    async def execute(self, payload: dict) -> None:

        try:

            response = await httpx.AsyncClient().post(f"{self.base_url}/api/legacy_erp_bridge", json=payload)

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