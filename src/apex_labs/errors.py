"""Domain errors surfaced by the CLI without tracebacks."""


class ApexLabsError(Exception):
    """Base class for expected Apex Labs errors."""


class ContractValidationError(ApexLabsError):
    """Input does not satisfy a versioned contract."""


class UnsupportedVersionError(ContractValidationError):
    """A contract version is not supported by this release."""


class IntegrityError(ApexLabsError):
    """A declared hash or cross-reference does not match its content."""


class IngestionError(ApexLabsError):
    """A source dataset cannot be safely ingested."""


class ExportError(ApexLabsError):
    """A product export cannot be generated safely."""


class AnalysisError(ApexLabsError):
    """A descriptive analysis run cannot be generated or verified safely."""


class EvidenceError(ApexLabsError):
    """A comparable evidence set cannot be built or verified safely."""


class InferenceError(ApexLabsError):
    """An inferential analysis cannot be produced or verified safely."""


class LifecycleError(ApexLabsError):
    """A hypothesis or finding lifecycle transition is not permitted."""
