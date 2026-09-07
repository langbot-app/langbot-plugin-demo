"""EventProcessor examples activated by explicit LangBot processor instances."""

from langbot_plugin.api.definition.plugin import BasePlugin


class EventProcessorDemo(BasePlugin):
    async def initialize(self) -> None:
        pass
