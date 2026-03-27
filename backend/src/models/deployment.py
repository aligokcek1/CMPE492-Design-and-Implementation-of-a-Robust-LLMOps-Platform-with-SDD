from enum import Enum
from pydantic import BaseModel


class ResourceType(str, Enum):
    CPU = "CPU"
    GPU = "GPU"


class DeploymentStatus(str, Enum):
    pending = "pending"
    mock_success = "mock_success"


class MockDeployment(BaseModel):
    model_repository: str
    resource_type: ResourceType
    deployment_status: DeploymentStatus = DeploymentStatus.pending


class MockDeploymentRequest(BaseModel):
    model_repository: str
    resource_type: ResourceType


class MockDeploymentResponse(BaseModel):
    status: str
    message: str
