import ast
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

from flake8_plugin_utils.utils import is_false, is_none

AnyFunctionDef = Union[ast.AsyncFunctionDef, ast.FunctionDef]


def get_qualname(node: ast.AST) -> Optional[str]:
    """
    If node represents a chain of attribute accesses, return is qualified name.
    """
    parts = []
    while True:
        if isinstance(node, ast.Name):
            parts.append(node.id)
            break
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        else:
            return None
    return '.'.join(reversed(parts))


class SimpleCallArgs(NamedTuple):
    args: Tuple[ast.AST, ...]
    kwargs: Dict[str, ast.AST]

    def get_argument(
        self, name: str, position: Optional[int] = None
    ) -> Optional[ast.AST]:
        """Get argument by name in kwargs or position in args."""
        kwarg = self.kwargs.get(name)
        if kwarg is not None:
            return kwarg
        if position is not None and len(self.args) > position:
            return self.args[position]
        return None


def get_simple_call_args(node: ast.Call) -> SimpleCallArgs:
    """
    Get call arguments which are specified explicitly (positional and keyword).
    """

    # list of leading non-starred args
    args = []
    for arg in node.args:
        if isinstance(arg, ast.Starred):
            break
        args.append(arg)

    # dict of keyword args
    keywords: Dict[str, ast.AST] = {}
    for keyword in node.keywords:
        if keyword.arg is not None:
            keywords[keyword.arg] = keyword.value

    return SimpleCallArgs(tuple(args), keywords)


def is_parametrize_call(node: ast.Call) -> bool:
    """Checks if given call is to `pytest.mark.parametrize`."""
    return get_qualname(node.func) == 'pytest.mark.parametrize'


def is_raises_call(node: ast.Call) -> bool:
    """Checks if given call is to `pytest.raises`."""
    return get_qualname(node.func) == 'pytest.raises'


def is_fail_call(node: ast.Call) -> bool:
    """Checks if given call is to `pytest.fail`."""
    return get_qualname(node.func) == 'pytest.fail'


def is_raises_with(node: ast.With) -> bool:
    """Checks that a given `with` statement has a `pytest.raises` context."""
    for item in node.items:
        if isinstance(item.context_expr, ast.Call) and is_raises_call(
            item.context_expr
        ):
            return True
    return False


class ParametrizeArgs(NamedTuple):
    names: ast.AST
    values: Optional[ast.AST]
    ids: Optional[ast.AST]


def extract_parametrize_call_args(node: ast.Call) -> Optional[ParametrizeArgs]:
    """Extracts argnames, argvalues and ids from a parametrize call."""
    args = get_simple_call_args(node)

    names_arg = args.get_argument('argnames', 0)
    if names_arg is None:
        return None

    values_arg = args.get_argument('argvalues', 1)
    ids_arg = args.get_argument('ids')
    return ParametrizeArgs(names_arg, values_arg, ids_arg)


def _is_pytest_fixture(node: ast.AST) -> bool:
    """Checks if node is a `pytest.fixture` attribute access."""
    return get_qualname(node) == 'pytest.fixture'


def is_pytest_yield_fixture(node: ast.AST) -> bool:
    """Checks if node is a `pytest.yield_fixture` attribute access."""
    return get_qualname(node) == 'pytest.yield_fixture'


def _is_any_pytest_fixture(node: ast.AST) -> bool:
    """Checks if node is a `pytest.fixture` or `pytest.yield_fixture`."""
    return _is_pytest_fixture(node) or is_pytest_yield_fixture(node)


def get_fixture_decorator(node: AnyFunctionDef) -> Union[ast.Call, ast.Attribute, None]:
    """
    Returns a @pytest.fixture decorator applied to given function definition, if any.

    Return value is either:
    * ast.Call, if decorator is written as @pytest.fixture()
    * ast.Attribute, if decorator is written as @pytest.fixture
    * None, if decorator not found
    """
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and _is_any_pytest_fixture(decorator.func)
        ):
            return decorator
        if isinstance(decorator, ast.Attribute) and _is_any_pytest_fixture(decorator):
            return decorator

    return None


def is_empty_string(node: ast.AST) -> bool:
    """
    Checks if the node is a constant empty string.
    """

    # empty string literal
    if isinstance(node, ast.Str) and not node.s:
        return True

    # empty f-string
    if isinstance(node, ast.JoinedStr) and not node.values:
        return True

    return False


def _is_empty_iterable(  # pylint:disable=too-many-return-statements
    node: ast.AST,
) -> bool:
    """
    Checks if the node is a constant empty iterable.
    """

    if is_empty_string(node):
        return True

    # empty list or tuple literal
    if isinstance(node, (ast.List, ast.Tuple)) and not node.elts:
        return True

    # empty dict literal
    if isinstance(node, ast.Dict) and not node.keys:
        return True

    if isinstance(node, ast.Call) and get_qualname(node.func) in (
        'list',
        'set',
        'tuple',
        'dict',
        'frozenset',
    ):
        if not node.args and not node.keywords:  # no args
            return True
        if (
            len(node.args) == 1
            and not node.keywords
            and _is_empty_iterable(node.args[0])
        ):  # single arg, empty iterable
            return True

    return False


def is_falsy_constant(node: ast.AST) -> bool:
    """
    Checks if the node is a constant with a falsy value.
    """

    # None or False constant
    if is_none(node) or is_false(node):
        return True

    # zero literal
    if isinstance(node, ast.Num) and not node.n:
        return True

    return _is_empty_iterable(node)


def is_test_function(node: AnyFunctionDef) -> bool:
    """Checks if the given function is a test function."""
    return node.name.startswith('test_')


def get_all_argument_names(node: ast.arguments) -> List[str]:
    """Returns a list of all argument names from the given node."""
    pos_only_args = getattr(node, 'posonlyargs', [])
    result = [arg.arg for arg in pos_only_args + node.args]
    if node.vararg:
        result.append(node.vararg.arg)
    result.extend([arg.arg for arg in node.kwonlyargs])
    if node.kwarg:
        result.append(node.kwarg.arg)
    return result
