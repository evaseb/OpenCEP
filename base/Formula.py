from abc import ABC  # Abstract Base Class


class Term(ABC):
    """
    Evaluates to the term's value.
    If there are variables (identifiers) in the term, a name-value binding shall be inputted.
    """
    def eval(self, binding: dict = None):
        raise NotImplementedError()

    def get_term_of(self, names: set):
        raise NotImplementedError()


class AtomicTerm(Term):
    """
    An atomic term of a formula in a condition (e.g., in "x*2 < y + 7" the atomic terms are 2 and 7).
    """
    def __init__(self, value: object):
        self.value = value

    def eval(self, binding: dict = None):
        return self.value

    def get_term_of(self, names: set):
        return self


class IdentifierTerm(Term):
    """
    A term of a formula representing a single variable (e.g., in "x*2 < y + 7" the atomic terms are x and y).
    """
    def __init__(self, name: str, getattr_func: callable):
        self.name = name
        self.getattr_func = getattr_func

    def eval(self, binding: dict = None):
        if not type(binding) == dict or self.name not in binding:
            raise NameError("Name %s is not bound to a value" % self.name)
        return self.getattr_func(binding[self.name])

    def get_term_of(self, names: set):
        if self.name in names:
            return self



class BinaryOperationTerm(Term):
    """
    A term representing a binary operation.
    """
    def __init__(self, lhs: Term, rhs: Term, binary_op: callable):
        self.lhs = lhs
        self.rhs = rhs
        self.binary_op = binary_op

    def eval(self, binding: dict = None):
        return self.binary_op(self.lhs.eval(binding), self.rhs.eval(binding))

    def get_term_of(self, names: set):
        raise NotImplementedError()


class PlusTerm(BinaryOperationTerm):
    def __init__(self, lhs: Term, rhs: Term):
        super().__init__(lhs, rhs, lambda x, y: x + y)

    def get_term_of(self, names: set):
        lhs = self.lhs.get_term_of(names)
        rhs = self.rhs.get_term_of(names)
        if lhs and rhs:
            return PlusTerm(lhs, rhs)


class MinusTerm(BinaryOperationTerm):
    def __init__(self, lhs: Term, rhs: Term):
        super().__init__(lhs, rhs, lambda x, y: x - y)

    def get_term_of(self, names: set):
        lhs = self.lhs.get_term_of(names)
        rhs = self.rhs.get_term_of(names)
        if lhs and rhs:
            return MinusTerm(lhs, rhs)


class MulTerm(BinaryOperationTerm):
    def __init__(self, lhs: Term, rhs: Term):
        super().__init__(lhs, rhs, lambda x, y: x * y)

    def get_term_of(self, names: set):
        lhs = self.lhs.get_term_of(names)
        rhs = self.rhs.get_term_of(names)
        if lhs and rhs:
            return MulTerm(lhs, rhs)


class DivTerm(BinaryOperationTerm):
    def __init__(self, lhs: Term, rhs: Term):
        super().__init__(lhs, rhs, lambda x, y: x / y)

    def get_term_of(self, names: set):
        lhs = self.lhs.get_term_of(names)
        rhs = self.rhs.get_term_of(names)
        if lhs and rhs:
            return DivTerm(lhs, rhs)


class Formula(ABC):
    """
    Returns whether the parameters satisfy the formula. It evaluates to True or False.
    If there are variables (identifiers) in the formula, a name-value binding shall be inputted.
    """
    def eval(self, binding: dict = None):
        pass

    def get_formula_of(self, names: set):
        pass

    def get_all_terms(self, term_set: set):
        NotImplementedError()


class AtomicFormula(Formula):
    """
    An atomic formula containing no logic operators (e.g., A < B).
    """
    def __init__(self, left_term: Term, right_term: Term, relation_op: callable):
        self.left_term = left_term
        self.right_term = right_term
        self.relation_op = relation_op

    def eval(self, binding: dict = None):
        return self.relation_op(self.left_term.eval(binding), self.right_term.eval(binding))

    def get_all_terms(self, term_set: set):
        if type(self.left_term) == IdentifierTerm:
            term_set.add(self.left_term.name)
        if type(self.right_term) == IdentifierTerm:
            term_set.add(self.right_term.name)
        return term_set



class EqFormula(AtomicFormula):
    def __init__(self, left_term: Term, right_term: Term):
        super().__init__(left_term, right_term, lambda x, y: x == y)

    def get_formula_of(self, names: set):
        right_term = self.right_term.get_term_of(names)
        left_term = self.left_term.get_term_of(names)
        if left_term and right_term:
            return EqFormula(left_term, right_term)

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_term = self.right_term
        left_term = self.left_term
        if left_term is None or right_term is None:
            return None
        if type(left_term) != IdentifierTerm or type(right_term) != IdentifierTerm:
            return None
        if type(left_term) == IdentifierTerm and left_term.name == name:
            return EqFormula(left_term, right_term)
        if type(right_term) == IdentifierTerm and right_term.name == name:
            return EqFormula(left_term, right_term)


class NotEqFormula(AtomicFormula):
    def __init__(self, left_term: Term, right_term: Term):
        super().__init__(left_term, right_term, lambda x, y: x != y)

    def get_formula_of(self, names: set):
        right_term = self.right_term.get_term_of(names)
        left_term = self.left_term.get_term_of(names)
        if left_term and right_term:
            return NotEqFormula(left_term, right_term)

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_term = self.right_term
        left_term = self.left_term
        if left_term is None or right_term is None:
            return None
        if type(left_term) != IdentifierTerm or type(right_term) != IdentifierTerm:
            return None
        if type(left_term) == IdentifierTerm and left_term.name == name:
            return NotEqFormula(left_term, right_term)
        if type(right_term) == IdentifierTerm and right_term.name == name:
            return NotEqFormula(left_term, right_term)

class GreaterThanFormula(AtomicFormula):
    def __init__(self, left_term: Term, right_term: Term):
        super().__init__(left_term, right_term, lambda x, y: x > y)

    def get_formula_of(self, names: set):
        right_term = self.right_term.get_term_of(names)
        left_term = self.left_term.get_term_of(names)
        if left_term and right_term:
            return GreaterThanFormula(left_term, right_term)

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_term = self.right_term
        left_term = self.left_term
        if left_term is None or right_term is None:
            return None
        if type(left_term) != IdentifierTerm or type(right_term) != IdentifierTerm:
            return None
        if type(left_term) == IdentifierTerm and left_term.name == name:
            return GreaterThanFormula(left_term, right_term)
        if type(right_term) == IdentifierTerm and right_term.name == name:
            return GreaterThanFormula(left_term, right_term)

class SmallerThanFormula(AtomicFormula):
    def __init__(self, left_term: Term, right_term: Term):
        super().__init__(left_term, right_term, lambda x, y: x < y)

    def get_formula_of(self, names: set):
        right_term = self.right_term.get_term_of(names)
        left_term = self.left_term.get_term_of(names)
        if left_term and right_term:
            return SmallerThanFormula(left_term, right_term)

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_term = self.right_term
        left_term = self.left_term
        if left_term is None or right_term is None:
            return None
        if type(left_term) != IdentifierTerm or type(right_term) != IdentifierTerm:
            return None
        if type(left_term) == IdentifierTerm and left_term.name == name:
            return SmallerThanFormula(left_term, right_term)
        if type(right_term) == IdentifierTerm and right_term.name == name:
            return SmallerThanFormula(left_term, right_term)

class GreaterThanEqFormula(AtomicFormula):
    def __init__(self, left_term: Term, right_term: Term):
        super().__init__(left_term, right_term, lambda x, y: x >= y)

    def get_formula_of(self, names: set):
        right_term = self.right_term.get_term_of(names)
        left_term = self.left_term.get_term_of(names)
        if left_term and right_term:
            return GreaterThanEqFormula(left_term, right_term)

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_term = self.right_term
        left_term = self.left_term
        if left_term is None or right_term is None:
            return None
        if type(left_term) != IdentifierTerm or type(right_term) != IdentifierTerm:
            return None
        if type(left_term) == IdentifierTerm and left_term.name == name:
            return GreaterThanEqFormula(left_term, right_term)
        if type(right_term) == IdentifierTerm and right_term.name == name:
            return GreaterThanEqFormula(left_term, right_term)

class SmallerThanEqFormula(AtomicFormula):
    def __init__(self, left_term: Term, right_term: Term):
        super().__init__(left_term, right_term, lambda x, y: x <= y)

    def get_formula_of(self, names: set):
        right_term = self.right_term.get_term_of(names)
        left_term = self.left_term.get_term_of(names)
        if left_term and right_term:
            return SmallerThanEqFormula(left_term, right_term)

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_term = self.right_term
        left_term = self.left_term
        if left_term is None or right_term is None:
            return None
        if type(left_term) != IdentifierTerm or type(right_term) != IdentifierTerm:
            return None
        if type(left_term) == IdentifierTerm and left_term.name == name:
            return SmallerThanEqFormula(left_term, right_term)
        if type(right_term) == IdentifierTerm and right_term.name == name:
            return SmallerThanEqFormula(left_term, right_term)

class BinaryLogicOpFormula(Formula):
    """
    A formula composed of a logic operator and two nested formulas.
    """
    def __init__(self, left_formula: Formula, right_formula: Formula, binary_logic_op: callable):
        self.left_formula = left_formula
        self.right_formula = right_formula
        self.binary_logic_op = binary_logic_op

    def eval(self, binding: dict = None):
        return self.binary_logic_op(self.left_formula.eval(binding), self.right_formula.eval(binding))

    def get_all_terms(self, term_set: set):
        self.left_formula.get_all_terms(term_set)
        self.right_formula.get_all_terms(term_set)
        return term_set



class AndFormula(BinaryLogicOpFormula):
    def __init__(self, left_formula: Formula, right_formula: Formula):
        super().__init__(left_formula, right_formula, lambda x, y: x and y)

    def get_formula_of(self, names: set):
        right_formula = self.right_formula.get_formula_of(names)
        left_formula = self.left_formula.get_formula_of(names)
        if left_formula is not None and right_formula is not None:
            return AndFormula(left_formula, right_formula)
        if left_formula:
            return left_formula
        if right_formula:
            return right_formula

    def get_events_in_a_condition_with(self, name: str):
        """
        Returns names of all events involved in the same condition as the event sent in param
        """
        right_formula = self.right_formula.get_events_in_a_condition_with(name)
        left_formula = self.left_formula.get_events_in_a_condition_with(name)
        if left_formula is not None and right_formula is not None:
            return AndFormula(left_formula, right_formula)
        if left_formula:
            return left_formula
        if right_formula:
            return right_formula

class TrueFormula(Formula):
    def eval(self, binding: dict = None):
        return True
