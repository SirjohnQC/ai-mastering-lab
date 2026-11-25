"""Pure validation for VST3 parameter overrides."""
def parse_parameter_overrides(value):
    """Validate persisted parameter overrides; return sorted index/value pairs."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1024:
        raise ValueError('parameter_overrides must be a list of at most 1024 entries')
    result = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {'index', 'value'}:
            raise ValueError('Each parameter override requires index and value')
        index, val = item['index'], item['value']
        if type(index) is not int or not (0 <= index <= 100000):
            raise ValueError('Parameter index must be a nonnegative integer')
        if type(val) not in (int, float) or not (0 <= val <= 1):
            raise ValueError('Normalized parameter value must be between 0 and 1')
        if index in result:
            raise ValueError('Duplicate parameter index')
        result[index] = float(val)
    return [(idx, result[idx]) for idx in sorted(result)]

