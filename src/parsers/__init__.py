"""
Parsers Package
Registry for all file format parsers.
"""

from src.parsers.netanya_parser import NetanyaParser
from src.parsers.netanya_d_parser import NetanyaDParser


# Registry: file_type → parser class
_PARSER_REGISTRY = {
    'netanya_format': NetanyaParser,
    'netanya_d_format': NetanyaDParser,
}


def get_parser_for_type(file_type: str):
    """
    Get the appropriate parser instance for a file type.
    Args: file_type: The file type identifier (e.g. 'netanya_format')
    Returns: Parser instance ready to use

    Raises:
        ValueError: If no parser exists for this file type
    """
    parser_class = _PARSER_REGISTRY.get(file_type)
    if not parser_class:
        supported = ', '.join(_PARSER_REGISTRY.keys())
        raise ValueError(
            f"אין parser לפורמט '{file_type}'. "
            f"פורמטים נתמכים: {supported}"
        )
    return parser_class()