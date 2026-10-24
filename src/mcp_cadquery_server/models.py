from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, model_validator
# Local dxl fork delta (ServaboFidem/mcp-cadquery, vs upstream eae44ca8):
# upstream used pydantic v1 `@root_validator` here, which pydantic v2
# rejects at import time. The FastMCP shim shares its process with the MCP
# SDK (`mcp>=2.2` requires pydantic v2), so the validator is ported to the
# v2 `@model_validator(mode="after")` instead of pinning pydantic<2.
# Behavior is unchanged: same checks, ValueError still surfaces as a
# ValidationError to the shim's argument handling.


class ExecuteCadqueryScriptArgs(BaseModel):
    workspace_path: str = Field(..., description="Path to the workspace directory")
    script: str = Field(..., description="CadQuery script content to execute")
    parameter_sets: Optional[List[Dict[str, Any]]] = Field(
        None, description="List of parameter dictionaries for multiple executions"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        None, description="Single parameter dictionary (converted to parameter_sets internally)"
    )

    @model_validator(mode="after")
    def check_params(self):
        param_sets, params = self.parameter_sets, self.parameters
        if param_sets is not None:
            if not isinstance(param_sets, list):
                raise ValueError("'parameter_sets' must be a list of dictionaries")
            if not all(isinstance(p, dict) for p in param_sets):
                raise ValueError("Each item in 'parameter_sets' must be a dictionary")
        if params is not None and not isinstance(params, dict):
            raise ValueError("'parameters' must be a dictionary")
        return self


class ExportShapeArgs(BaseModel):
    workspace_path: str = Field(..., description="Path to the workspace directory")
    result_id: str = Field(..., description="Result ID from script execution")
    shape_index: int = Field(0, description="Index of the shape in the result list")
    filename: str = Field(..., description="Target filename or path for export")
    format: Optional[str] = Field(None, description="Export format (e.g., STEP, STL)")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Export options dictionary")


class ExportShapeToSvgArgs(BaseModel):
    workspace_path: str = Field(..., description="Path to the workspace directory")
    result_id: str = Field(..., description="Result ID from script execution")
    shape_index: int = Field(0, description="Index of the shape in the result list")
    filename: Optional[str] = Field(None, description="Optional target filename for SVG export")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="SVG export options dictionary")


class ScanPartLibraryArgs(BaseModel):
    workspace_path: Optional[str] = Field(None, description="Path to the part library directory (defaults to active library)")


class SaveWorkspaceModuleArgs(BaseModel):
    workspace_path: str = Field(..., description="Path to the workspace directory")
    module_filename: str = Field(..., description="Module filename (must end with .py)")
    module_content: str = Field(..., description="Python module content (can be empty string)")


class InstallWorkspacePackageArgs(BaseModel):
    workspace_path: str = Field(..., description="Path to the workspace directory")
    package_name: str = Field(..., description="Name of the package to install")


class SearchPartsArgs(BaseModel):
    query: Optional[str] = Field("", description="Search query string (empty returns all parts)")


class GetShapePropertiesArgs(BaseModel):
    result_id: str = Field(..., description="Result ID from script execution")
    shape_index: int = Field(0, description="Index of the shape in the result list")


class GetShapeDescriptionArgs(BaseModel):
    result_id: str = Field(..., description="Result ID from script execution")
    shape_index: int = Field(0, description="Index of the shape in the result list")