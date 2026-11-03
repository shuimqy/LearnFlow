from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_serializer


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", check_fields=False)
    def serialize_dates(self, value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=value.tzinfo or UTC).isoformat()
        return value
