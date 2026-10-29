"""Public failures contain categories, never raw provider exceptions or credentials."""


class GenerationFailure(RuntimeError):
    def __init__(self, stage, kind):
        self.stage, self.kind = stage, kind
        super().__init__(f"{stage}: {kind}")


class LLMCallError(GenerationFailure):
    pass
