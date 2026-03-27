import asyncio
from ..models.deployment import MockDeploymentResponse, ResourceType


async def mock_deploy(model_repository: str, resource_type: ResourceType) -> MockDeploymentResponse:
    """Simulate a GCP deployment with a short artificial delay."""
    await asyncio.sleep(2)
    return MockDeploymentResponse(
        status="mock_success",
        message=(
            f"Mock deployment of '{model_repository}' on {resource_type.value} completed successfully."
        ),
    )
