from typing import Any

_ERROR_REF = "#/components/schemas/Error"
_GAME_RESPONSE_REF = "#/components/schemas/GameResponse"
_GAME_CREATE_REF = "#/components/schemas/GameCreateRequest"
_GAME_UPDATE_REF = "#/components/schemas/GameUpdateRequest"
_STATUS_CHANGE_REF = "#/components/schemas/StatusChangeResponse"
_FILE_UPLOAD_REF = "#/components/schemas/FileUploadResponse"
_GAME_FILE_UPLOAD_REF = "#/components/schemas/GameFileUploadResponse"


def get_openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "IFDB REST API",
            "version": "1.0.0",
            "description": (
                "REST API for creating, reading, updating games, managing "
                "publication state, and uploading game files on IFDB."
            ),
        },
        "servers": [{"url": "/"}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "API token passed as 'Authorization: Bearer <token>'"
                    ),
                },
                "TokenAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": (
                        "API token passed as 'Authorization: Token <token>'"
                    ),
                },
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["error"],
                },
                "GameResponse": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "title": {"type": "string"},
                        "state": {
                            "type": "string",
                            "enum": ["draft", "published"],
                        },
                        "revision_id": {"type": "integer", "nullable": True},
                        "canonical_text": {"type": "string"},
                        "created_at": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "updated_at": {
                            "type": "string",
                            "format": "date-time",
                        },
                    },
                    "required": ["id", "state", "canonical_text"],
                },
                "GameCreateRequest": {
                    "type": "object",
                    "properties": {
                        "canonical_text": {
                            "type": "string",
                            "description": (
                                "YAML frontmatter + markdown body"
                            ),
                        },
                        "state": {
                            "type": "string",
                            "enum": ["draft", "published"],
                            "default": "draft",
                            "description": "Initial state (default draft)",
                        },
                    },
                    "required": ["canonical_text"],
                },
                "GameUpdateRequest": {
                    "type": "object",
                    "properties": {
                        "canonical_text": {
                            "type": "string",
                            "description": "Updated canonical text",
                        }
                    },
                    "required": ["canonical_text"],
                },
                "StatusChangeResponse": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "state": {
                            "type": "string",
                            "enum": ["draft", "published"],
                        },
                    },
                    "required": ["id", "state"],
                },
                "FileUploadResponse": {
                    "type": "object",
                    "properties": {
                        "url_id": {"type": "integer"},
                        "url": {"type": "string"},
                        "filename": {"type": "string"},
                        "canonical_snippet": {
                            "type": "array",
                            "items": {},
                            "example": ["download_direct", "", 123],
                        },
                    },
                    "required": [
                        "url_id",
                        "url",
                        "filename",
                        "canonical_snippet",
                    ],
                },
                "GameFileUploadResponse": {
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "integer"},
                        "url_id": {"type": "integer"},
                        "url": {"type": "string"},
                        "filename": {"type": "string"},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "canonical_snippet": {
                            "type": "array",
                            "items": {},
                            "example": ["download_direct", "Package", 123],
                        },
                        "canonical_text": {"type": "string"},
                    },
                    "required": [
                        "game_id",
                        "url_id",
                        "url",
                        "filename",
                        "category",
                        "canonical_snippet",
                    ],
                },
            },
        },
        "security": [{"BearerAuth": []}, {"TokenAuth": []}],
        "paths": {
            "/api/v1/games/": {
                "post": {
                    "summary": "Create a game",
                    "description": (
                        "Creates a new game from canonical text. Defaults to "
                        "draft state. Accepts JSON or raw text/plain."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": _GAME_CREATE_REF}
                            },
                            "text/plain": {
                                "schema": {
                                    "type": "string",
                                    "description": "Raw canonical text",
                                }
                            },
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Game created successfully",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _GAME_RESPONSE_REF}
                                }
                            },
                        },
                        "400": {
                            "description": "Bad request",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _ERROR_REF}
                                }
                            },
                        },
                        "401": {
                            "description": "Unauthorized",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _ERROR_REF}
                                }
                            },
                        },
                        "403": {
                            "description": "Forbidden",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _ERROR_REF}
                                }
                            },
                        },
                    },
                }
            },
            "/api/v1/games/{id}/": {
                "get": {
                    "summary": "Get a game",
                    "description": (
                        "Retrieves game metadata and canonical text."
                    ),
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Game details",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _GAME_RESPONSE_REF}
                                }
                            },
                        },
                        "404": {
                            "description": "Game not found",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _ERROR_REF}
                                }
                            },
                        },
                    },
                },
                "put": {
                    "summary": "Update a game",
                    "description": (
                        "Updates game metadata and revision by passing "
                        "canonical text."
                    ),
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": _GAME_UPDATE_REF}
                            },
                            "text/plain": {
                                "schema": {
                                    "type": "string",
                                    "description": "Raw canonical text",
                                }
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Game updated",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _GAME_RESPONSE_REF}
                                }
                            },
                        },
                        "404": {
                            "description": "Game not found",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _ERROR_REF}
                                }
                            },
                        },
                    },
                },
            },
            "/api/v1/games/{id}/publish/": {
                "post": {
                    "summary": "Publish a game",
                    "description": (
                        "Transitions game status from draft to published."
                    ),
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Game published",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _STATUS_CHANGE_REF}
                                }
                            },
                        }
                    },
                }
            },
            "/api/v1/games/{id}/unpublish/": {
                "post": {
                    "summary": "Unpublish a game",
                    "description": (
                        "Transitions game status from published to draft."
                    ),
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Game unpublished",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _STATUS_CHANGE_REF}
                                }
                            },
                        }
                    },
                }
            },
            "/api/v1/files/": {
                "post": {
                    "summary": "Upload a standalone file",
                    "description": (
                        "Uploads a file to generate a download link."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                        }
                                    },
                                    "required": ["file"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "File uploaded",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _FILE_UPLOAD_REF}
                                }
                            },
                        }
                    },
                }
            },
            "/api/v1/games/{id}/files/": {
                "post": {
                    "summary": "Upload a file attached to a game",
                    "description": (
                        "Uploads a file and links it as a download link on "
                        "the specified game."
                    ),
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                        },
                                        "category": {
                                            "type": "string",
                                            "default": "download_direct",
                                        },
                                        "description": {
                                            "type": "string",
                                            "default": "",
                                        },
                                    },
                                    "required": ["file"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": (
                                "File uploaded and attached to game"
                            ),
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": _GAME_FILE_UPLOAD_REF}
                                }
                            },
                        }
                    },
                }
            },
        },
    }
