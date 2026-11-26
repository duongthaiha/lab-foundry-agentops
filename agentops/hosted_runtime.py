"""Hosted Responses adapter preserving actual upstream MCP items and token usage."""

import asyncio
import os

from azure.ai.agentserver.responses import ResponseEventStream, ResponsesAgentServerHost

from .contracts import LabError, parse_json, require


async def respond(user_input: str, project, metadata: dict) -> dict:
    tools = parse_json(os.environ["DELIVERY_TOOLS_JSON"])
    require({tool["server_label"] for tool in tools} == {"knowledge-base", "lab-tools"},
            "Both real MCP dependencies are required")
    require(bool(user_input.strip()), "User input is required")
    negative = os.environ["DELIVERY_NEGATIVE_CONTROL"] == "true"
    async with project.get_openai_client(max_retries=0, timeout=60) as client:
        response = await client.responses.create(
            model=os.environ["FOUNDRY_MODEL_NAME"],
            instructions=os.environ["DELIVERY_INSTRUCTIONS"] if not negative else "Do not call tools. Return {}.",
            input=user_input, tools=tools, tool_choice="none" if negative else "auto",
            max_output_tokens=1024, metadata=metadata, store=False,
        )
        return response.model_dump(mode="json")


async def events(request, response_id: str, response: dict):
    require(response["status"] == "completed", "Upstream runtime did not complete")
    require(response.get("usage") is not None, "Upstream token usage missing")
    stream = ResponseEventStream(response_id=response_id, request=request)
    yield stream.emit_created()
    yield stream.emit_in_progress()
    for item in response["output"]:
        builder = stream.add_output_item(item["id"])
        yield builder.emit_added(item)
        yield builder.emit_done(item)
    yield stream.emit_completed(usage=response["usage"])


def create_app(project):
    app = ResponsesAgentServerHost()

    @app.response_handler
    async def handler(request, context, cancellation_signal):
        from azure.core.exceptions import AzureError
        from openai import OpenAIError

        user_input = await context.get_input_text()
        require(isinstance(user_input, str), "Text input required")
        work = asyncio.create_task(respond(user_input, project, request.get("metadata") or {}))
        cancelled = asyncio.create_task(cancellation_signal.wait())
        shutdown = asyncio.create_task(context.shutdown.wait())
        try:
            done, _ = await asyncio.wait((work, cancelled, shutdown), return_when=asyncio.FIRST_COMPLETED)
            if cancelled in done or shutdown in done:
                raise asyncio.CancelledError()
            try:
                response = await work
            except (AzureError, OpenAIError):
                raise LabError("Hosted dependency invocation failed; inspect private service telemetry") from None
            return events(request, context.response_id, response)
        finally:
            for task in (work, cancelled, shutdown):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, cancelled, shutdown, return_exceptions=True)

    return app


async def serve():
    from azure.ai.projects.aio import AIProjectClient
    from azure.identity.aio import DefaultAzureCredential

    async with DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
        async with AIProjectClient(os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential,
                                   allow_preview=True, retry_total=0) as project:
            await create_app(project).run_async(port=8088)


if __name__ == "__main__":
    asyncio.run(serve())
