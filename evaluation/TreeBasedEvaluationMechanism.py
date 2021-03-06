from abc import ABC
from datetime import timedelta, datetime
from base.Pattern import Pattern
from base.PatternStructure import SeqOperator, QItem, NegationOperator, AndOperator, OrOperator
from base.Formula import TrueFormula, Formula
from evaluation.PartialMatch import PartialMatch
from misc.IOUtils import Stream
from typing import List, Tuple
from base.Event import Event
from misc.Utils import merge, merge_according_to, is_sorted, find_partial_match_by_timestamp, get_index, \
    find_positive_events_before
from base.PatternMatch import PatternMatch
from evaluation.EvaluationMechanism import EvaluationMechanism, NegationMode
#from evaluation.EvaluationMechanismFactory import NegationMode
from queue import Queue


class Node(ABC):
    """
    This class represents a single node of an evaluation tree.
    """

    def __init__(self, sliding_window: timedelta, parent):
        self._parent = parent
        self._sliding_window = sliding_window
        self._partial_matches = []
        self._condition = TrueFormula()
        # matches that were not yet pushed to the parent for further processing => waiting for a potential not yhat could invalidate our match
        self._unhandled_partial_matches = Queue()

    def consume_first_partial_match(self):
        """
        Removes and returns a single partial match buffered at this node.
        Used in the root node to collect full pattern matches.
        """
        ret = self._partial_matches[0]
        del self._partial_matches[0]
        return ret

    def has_partial_matches(self):
        """
        Returns True if this node contains any partial matches and False otherwise.
        """
        return len(self._partial_matches) > 0

    def get_last_unhandled_partial_match(self):
        """
        Returns the last partial match buffered at this node and not yet transferred to its parent.
        """
        return self._unhandled_partial_matches.get()

    def set_parent(self, parent):
        """
        Sets the parent of this node.
        """
        self._parent = parent

    def get_root(self):
        """
        Get root of tree
        """
        node = self
        while node._parent is not None:
            node = node._parent
        return node

    def clean_expired_partial_matches(self, last_timestamp: datetime):
        """
        Removes partial matches whose earliest timestamp violates the time window constraint.
        """
        if self._sliding_window == timedelta.max:
            return
        count = find_partial_match_by_timestamp(self._partial_matches, last_timestamp - self._sliding_window)
        self._partial_matches = self._partial_matches[count:]

        """
        "waiting for timeout" contains matches that may be invalidated by a future negative event
        if the timestamp has passed, they can't be invalidated anymore,
        therefore we remove them from waiting for timeout
        and we put them in the field "matches to handle at eof" of the root,
        for it to put it in the matches at the end of the program
        """

        if (type(self) == PostProcessingNode or type(self) == FirstChanceNode) \
                and self.is_last:
            self.waiting_for_time_out = sorted(self.waiting_for_time_out, key=lambda x: x.first_timestamp)
            count = find_partial_match_by_timestamp(self.waiting_for_time_out, last_timestamp - self._sliding_window)
            node = self.get_root()

            node.matches_to_handle_at_EOF.extend(self.waiting_for_time_out[:count])
            self.waiting_for_time_out = self.waiting_for_time_out[count:]

        """
        the end of the function is here to handle a special case: a pattern that starts by a negative event, and we got
        a negative event that has invalidated the first part of a match but the second part of the match arrives later,
        with a timestamp not "influenced" anymore by the negative event
        example: notA, B, C : A has invalidated B, but C arrives later,
        and the time window doesn't contain A and C at the same time. Therefore B, C is a match.
        If a positive event (C) arrives with a timestamp that exceeds the frame of the negative event (A),
        we want to remove the negative event and try to handle previous pm that were blocked by A (in our case: B)
        Algorithm : we get all the FirstChanceNodes with flag is_first in the subtree of the current node
        for each node, we remove the expired negative events, and we send back to the tree
        all the pms contained in the field "check_expired_timestamp" that have been blocked
        by a negative event that has expired.
        """

        if self._parent is not None:
            list_of_nodes = self._parent.get_first_FCNodes()
        else:
            list_of_nodes = self.get_first_FCNodes()

        for node in list_of_nodes:
            if node._sliding_window == timedelta.max:
                    return
            count = find_partial_match_by_timestamp(node._right_subtree._partial_matches,
                                                    last_timestamp - node._right_subtree._sliding_window)
            node._right_subtree._partial_matches = node._right_subtree._partial_matches[count:]

            partial_matches = [pm for timestamp, pm in node.check_expired_timestamp if timestamp < last_timestamp]
            for pm in partial_matches:

                """
                "unblocking" previous pms that were blocked by an expired neg event may lead to accept as a match
                a pam that is in the time window of the negative event.
                In our previous example, if a C1 arrived earlier and was blocked by A (like it should be),
                removing the A now will cause C1 to go up the tree. Therefore we hold a threshold in a node,
                which is the timestamp that a pm has tà exceed to be a match
                (when B, C1 go all the way up, we want to stop them because they are still in the time window of the previous A)
                By default, the threshold is old by the root. If the root is a FirstChance Node with flag is_last on,
                it may cause errors, and therefore we go down the tree from the root until we find a node that meets the criteria
                """

                node_to_hold_threshold = self.get_root()

                while type(node_to_hold_threshold) == FirstChanceNode and node_to_hold_threshold.is_last:
                    node_to_hold_threshold = node_to_hold_threshold._left_subtree

                node_to_hold_threshold.threshold = last_timestamp

                # we want to remove the pm from the check_expired_timestamp list
                node.check_expired_timestamp = [x for x in node.check_expired_timestamp if x[1] != pm]

                node._left_subtree._unhandled_partial_matches.put(pm)
                node.handle_new_partial_match(node._left_subtree)

                # now we turn the threshold off because we finished to handle this case
                node_to_hold_threshold.threshold = 0

    def add_partial_match(self, pm: PartialMatch):
        """
        Registers a new partial match at this node.
        As of now, the insertion is always by the timestamp, and the partial matches are stored in a list sorted by
        timestamp. Therefore, the insertion operation is performed in O(log n).
        """
        index = find_partial_match_by_timestamp(self._partial_matches, pm.first_timestamp)
        self._partial_matches.insert(index, pm)
        if self._parent is not None:
            self._unhandled_partial_matches.put(pm)

    def get_partial_matches(self):
        """
        Returns the currently stored partial matches.
        """
        return self._partial_matches

    def get_first_FCNodes(self):
        """
        Returns all FirstChance nodes with flag is_first on in the subtree of self - to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_leaves(self):
        """
        Returns all leaves in this tree - to be implemented by subclasses.
        """
        raise NotImplementedError()

    def apply_formula(self, formula: Formula):
        """
        Applies a given formula on all nodes in this tree - to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_event_definitions(self):
        """
        Returns the specifications of all events collected by this tree - to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_deepest_leave(self):

        raise NotImplementedError()


class LeafNode(Node):
    """
    A leaf node is responsible for a single event type of the pattern.
    """

    def __init__(self, sliding_window: timedelta, leaf_index: int, leaf_qitem: QItem, parent: Node):
        super().__init__(sliding_window, parent)
        self.__leaf_index = leaf_index
        self.__event_name = leaf_qitem.name
        self.__event_type = leaf_qitem.event_type

        # We added an index for every QItem according to its place in the pattern to get the right order in
        # field "event_def"
        self.qitem_index = leaf_qitem.get_event_index()

    def get_leaves(self):
        return [self]

    def get_first_FCNodes(self):
        return []

    def get_deepest_leave(self):
        return self

    def set_qitem_index(self, index: int):
        self.qitem_index = index

    def apply_formula(self, formula: Formula):
        condition = formula.get_formula_of(self.__event_name)
        if condition is not None:
            self._condition = condition

    def get_event_definitions(self):
        return [(self.__leaf_index, QItem(self.__event_type, self.__event_name, self.qitem_index))]

    def get_event_type(self):
        """
        Returns the type of events processed by this leaf.
        """
        return self.__event_type

    def handle_event(self, event: Event):
        """
        Inserts the given event to this leaf.
        """
        self.clean_expired_partial_matches(event.timestamp)

        # get event's qitem and make a binding to evaluate formula for the new event.
        binding = {self.__event_name: event.payload}

        if not self._condition.eval(binding):
            return

        self.add_partial_match(PartialMatch([event]))
        if self._parent is not None:
            self._parent.handle_new_partial_match(self)

    def get_event_name(self):
        """
        Returns the name of the event processed by this leaf.
        """
        return self.__event_name


class InternalNode(Node):
    """
    An internal node connects two subtrees, i.e., two subpatterns of the evaluated pattern.
    """

    def __init__(self, sliding_window: timedelta, parent: Node = None, event_defs: List[Tuple[int, QItem]] = None,
                 left: Node = None, right: Node = None):
        super().__init__(sliding_window, parent)
        self._event_defs = event_defs
        self._left_subtree = left
        self._right_subtree = right
        """
        Special field to be used in only one node (root or first node which is not a FC node) if the pattern contains
        a negative operator, in mode "first chance negation".
        In some cases, contains the threshold timestamp that a pm has to exceed in order to be a match - see clean_expired
        Otherwise is 0
        """
        self.threshold = 0

    def get_leaves(self):
        result = []
        if self._left_subtree is not None:
            result += self._left_subtree.get_leaves()
        if self._right_subtree is not None:
            result += self._right_subtree.get_leaves()
        return result

    def get_first_FCNodes(self):
        result = []
        if type(self._left_subtree) != LeafNode:
            result += self._left_subtree.get_first_FCNodes()
        if type(self._right_subtree) != LeafNode:
            result += self._right_subtree.get_first_FCNodes()
        return result

    def get_deepest_leave(self):
        if self._left_subtree is not None:
            return self._left_subtree.get_deepest_leave()

    def apply_formula(self, formula: Formula):
        names = {item[1].name for item in self._event_defs}
        condition = formula.get_formula_of(names)
        self._condition = condition if condition else TrueFormula()
        self._left_subtree.apply_formula(self._condition)
        self._right_subtree.apply_formula(self._condition)

    def get_event_definitions(self):
        return self._event_defs

    def _set_event_definitions(self,
                               left_event_defs: List[Tuple[int, QItem]], right_event_defs: List[Tuple[int, QItem]]):
        """
        A helper function for collecting the event definitions from subtrees. To be overridden by subclasses.
        """
        self._event_defs = left_event_defs + right_event_defs

    def set_subtrees(self, left: Node, right: Node):
        """
        Sets the subtrees of this node.
        """
        self._left_subtree = left
        self._right_subtree = right
        self._set_event_definitions(self._left_subtree.get_event_definitions(),
                                    self._right_subtree.get_event_definitions())

    def handle_new_partial_match(self, partial_match_source: Node):
        """
        Internal node's update for a new partial match in one of the subtrees.
        """
        if partial_match_source == self._left_subtree:
            other_subtree = self._right_subtree
        elif partial_match_source == self._right_subtree:
            other_subtree = self._left_subtree
        else:
            raise Exception()  # should never happen

        new_partial_match = partial_match_source.get_last_unhandled_partial_match()
        first_event_defs = partial_match_source.get_event_definitions()
        other_subtree.clean_expired_partial_matches(new_partial_match.last_timestamp)
        partial_matches_to_compare = other_subtree.get_partial_matches()
        second_event_defs = other_subtree.get_event_definitions()

        self.clean_expired_partial_matches(new_partial_match.last_timestamp)

        # given a partial match from one subtree, for each partial match
        # in the other subtree we check for new partial matches in this node.
        for partialMatch in partial_matches_to_compare:
            self._try_create_new_match(new_partial_match, partialMatch, first_event_defs, second_event_defs)

    def _try_create_new_match(self,
                              first_partial_match: PartialMatch, second_partial_match: PartialMatch,
                              first_event_defs: List[Tuple[int, QItem]], second_event_defs: List[Tuple[int, QItem]]):
        """
        Verifies all the conditions for creating a new partial match and creates it if all constraints are satisfied.
        """
        if self._sliding_window != timedelta.max and \
                abs(first_partial_match.last_timestamp - second_partial_match.first_timestamp) > self._sliding_window:
            return
        events_for_new_match = self._merge_events_for_new_match(first_event_defs, second_event_defs,
                                                                first_partial_match.events, second_partial_match.events)

        if not self._validate_new_match(events_for_new_match):
            return

        # If the threshold is not 0, we accept the pm as a match only if its last timestamp exceeds the threshold
        if self.threshold != 0 and first_partial_match.last_timestamp < self.threshold:
            return

        self.add_partial_match(PartialMatch(events_for_new_match))
        if self._parent is not None:
            self._parent.handle_new_partial_match(self)

    def _merge_events_for_new_match(self,
                                    first_event_defs: List[Tuple[int, QItem]],
                                    second_event_defs: List[Tuple[int, QItem]],
                                    first_event_list: List[Event],
                                    second_event_list: List[Event]):
        """
        Creates a list of events to be included in a new partial match.
        """
        if self._event_defs[0][0] == first_event_defs[0][0]:
            return first_event_list + second_event_list
        if self._event_defs[0][0] == second_event_defs[0][0]:
            return second_event_list + first_event_list
        raise Exception()

    def _validate_new_match(self, events_for_new_match: List[Event]):
        """
        Validates the condition stored in this node on the given set of events.
        """
        binding = {
            self._event_defs[i][1].name: events_for_new_match[i].payload for i in range(len(self._event_defs))
        }
        return self._condition.eval(binding)


class AndNode(InternalNode):
    """
    An internal node representing an "AND" operator.
    """
    pass


class SeqNode(InternalNode):
    """
    An internal node representing a "SEQ" (sequence) operator.
    In addition to checking the time window and condition like the basic node does, SeqNode also verifies the order
    of arrival of the events in the partial matches it constructs.
    """

    def _set_event_definitions(self,
                               left_event_defs: List[Tuple[int, QItem]], right_event_defs: List[Tuple[int, QItem]]):
        self._event_defs = merge(left_event_defs, right_event_defs, key=lambda x: x[0])

    def _merge_events_for_new_match(self,
                                    first_event_defs: List[Tuple[int, QItem]],
                                    second_event_defs: List[Tuple[int, QItem]],
                                    first_event_list: List[Event],
                                    second_event_list: List[Event]):
        return merge_according_to(first_event_defs, second_event_defs,
                                  first_event_list, second_event_list, key=lambda x: x[0])

    def _validate_new_match(self, events_for_new_match: List[Event]):
        if not is_sorted(events_for_new_match, key=lambda x: x.timestamp):
            return False
        return super()._validate_new_match(events_for_new_match)


class InternalNegationNode(InternalNode):
    """
    Virtual class that represents a NOT operator. Has two subclasses, one for each mode
    """
    def __init__(self, sliding_window: timedelta, is_first: bool, is_last: bool, top_operator, parent: Node = None,
                 event_defs: List[Tuple[int, QItem]] = None,
                 left: Node = None, right: Node = None):
        super().__init__(sliding_window, parent, event_defs, left, right)

        """
            Negation operators that have no "positive" operators before them in the pattern have the flag is_first on
            Negation operators that have no "positive" operators after them in the pattern have the flag is_last on
        """
        self.is_first = is_first
        self.is_last = is_last
        self.top_operator = top_operator

        """
        Contains PMs that match the pattern, but may be invalidated by a negative event later (when the pattern ends
        with a not operator)
        We wait for them to exceed the time window and therefore can't be invalidated anymore
        """
        self.waiting_for_time_out = []

        """
        Contains PMs that match the whole pattern and were in waiting_for_timeout, and now can't be invalidated anymore
        When we finish all the stream of events we handle them and put them in the output
        """
        self.matches_to_handle_at_EOF = []

    def _set_event_definitions(self,
                               left_event_defs: List[Tuple[int, QItem]], right_event_defs: List[Tuple[int, QItem]]):
        self._event_defs = merge(left_event_defs, right_event_defs, key=get_index)

    def get_event_definitions(self):  # to support multiple neg
        return self._left_subtree.get_event_definitions()  # à verifier

    def _try_create_new_match(self,
                              first_partial_match: PartialMatch, second_partial_match: PartialMatch,
                              first_event_defs: List[Tuple[int, QItem]], second_event_defs: List[Tuple[int, QItem]]):

        if self._sliding_window != timedelta.max and \
                abs(first_partial_match.last_timestamp - second_partial_match.first_timestamp) > self._sliding_window:
            return

        events_for_new_match = merge_according_to(first_event_defs, second_event_defs,
                                                  first_partial_match.events, second_partial_match.events,
                                                  key=get_index)

        if self.top_operator == SeqOperator:
            if not is_sorted(events_for_new_match, key=lambda x: x.timestamp):
                return False
        elif self.top_operator == AndOperator:
            """
                To be implemented later when class AndNode will be implemented
            """
            raise NotImplementedError()
        elif self.top_operator == OrOperator:
            """
                To be implemented later when class OrNode will be implemented
            """
            raise NotImplementedError()

        return self._validate_new_match(events_for_new_match)

    def handle_PM_with_negation_at_the_end(self, partial_match_source: Node):
        """
        Customized handle_new_partial_matches function in case of a new pm matching a not operator at the end of the pattern:
        The PMs to compare come from "get_waiting_for_timeout" and not from "get_partial_matches": these are PMs that
        match the pattern but may be invalidated by a later not operator at the end of a pattern.
        We check which ones have been invalidated and we discard them. The others will be final matches once there are
        no future not event that can invalidate them == when the time window has ended
        """

        other_subtree = self.get_first_last_negative_node()

        new_partial_match = partial_match_source.get_last_unhandled_partial_match()
        first_event_defs = partial_match_source.get_event_definitions()
        other_subtree.clean_expired_partial_matches(new_partial_match.last_timestamp)

        partial_matches_to_compare = other_subtree.waiting_for_time_out
        second_event_defs = other_subtree.get_event_definitions()
        self.clean_expired_partial_matches(new_partial_match.last_timestamp)

        matches_to_keep = []
        for partialMatch in partial_matches_to_compare:
            if not self._try_create_new_match(new_partial_match, partialMatch, first_event_defs, second_event_defs):
                matches_to_keep.append(partialMatch)

        other_subtree.waiting_for_time_out = matches_to_keep

    def get_first_last_negative_node(self):
        """
        This function descends in the tree and returns the first Node that is not a NegationNode at the end
        of the Pattern. That's in that node that we keep the PMs that are waiting for timeout: we block them here,
        because if they go directly up to the root they are automatically added to the matches
        """
        if (type(self._left_subtree) == PostProcessingNode or type(self._left_subtree) == FirstChanceNode) \
                and self._left_subtree.is_last:
            return self._left_subtree.get_first_last_negative_node()
        else:
            return self

    def _remove_partial_matches(self, matches_to_remove: List[PartialMatch]):
        """
        Remove list of partial match from a node
        """
        matches_to_keep = [match for match in self._partial_matches if match not in matches_to_remove]
        self._partial_matches = matches_to_keep


class FirstChanceNode(InternalNegationNode):
    """
        An internal node representing a Negation operator in case of FirstChance mode

    """
    def __init__(self, sliding_window: timedelta, is_first: bool, is_last: bool, top_operator, parent: Node = None,
                 event_defs: List[Tuple[int, QItem]] = None,
                 left: Node = None, right: Node = None):
        super().__init__(sliding_window, is_first, is_last, top_operator, parent, event_defs, left, right)

        """
        contains PMs invalidated by a negative event at the beginning of the pattern
        but may be part of a longer pm that exceeds the time window of the neg event later - see clean_expired
        """
        self.check_expired_timestamp = []

    def handle_new_partial_match(self, partial_match_source: Node):

        if partial_match_source == self._left_subtree:
            # If we received events from the left_subtree => positive events
            # we add them to the partial matches of this node and if no previously arrived negative event
            # invalidate them we go up in the tree with handle new partial match
            new_partial_match = partial_match_source.get_last_unhandled_partial_match()
            other_subtree = self._right_subtree

            if self.is_last:
                # if self.is_last, the only events left in the pattern are negative ones.
                # if we get no future negative events, we have a match -> special handling,
                # see function handle_PM_with_negation_at_the_end
                self.waiting_for_time_out.append(new_partial_match)
                return

            first_event_defs = partial_match_source.get_event_definitions()
            other_subtree.clean_expired_partial_matches(new_partial_match.last_timestamp)

            partial_matches_to_compare = other_subtree.get_partial_matches()
            second_event_defs = other_subtree.get_event_definitions()
            self.clean_expired_partial_matches(new_partial_match.last_timestamp)

            invalidate = False
            partialMatch = None
            for partialMatch in partial_matches_to_compare:
                # for every negative event, we want to check if he invalidates new_partial_match
                if self._try_create_new_match(new_partial_match, partialMatch, first_event_defs, second_event_defs):
                    invalidate = True
                    break

            # if the flag is off, there is no negative event that invalidated the current pm and therefore we go up
            if invalidate is False:
                self.add_partial_match(new_partial_match)
                if self._parent is not None:
                    self._parent.handle_new_partial_match(self)

            if invalidate and self.is_first:
                # if the new partial match is invalidated we want to check later if the negative event has expired,
                # so we keep the timestamp until which this negative event will expire
                self.check_expired_timestamp.append((partialMatch.last_timestamp + self._sliding_window,
                                                     new_partial_match))
            return

        elif partial_match_source == self._right_subtree:
            # the current pm is a negative event, we check if it invalidates previous pms
            if self.is_first:
                return
            elif self.is_last:
                self.handle_PM_with_negation_at_the_end(partial_match_source)
                return
            else:
                new_partial_match = partial_match_source.get_last_unhandled_partial_match()

                other_subtree = self._left_subtree

                first_event_defs = partial_match_source.get_event_definitions()
                other_subtree.clean_expired_partial_matches(new_partial_match.last_timestamp)

                partial_matches_to_compare = other_subtree.get_partial_matches()
                second_event_defs = other_subtree.get_event_definitions()
                self.clean_expired_partial_matches(new_partial_match.last_timestamp)

                partial_match_to_remove = []
                for partialMatch in partial_matches_to_compare:
                    if self._try_create_new_match(new_partial_match, partialMatch, first_event_defs, second_event_defs):
                        partial_match_to_remove.append(partialMatch)

                # if the negative event invalidated some pms we want to remove all of them in each negative node in the way up
                node = self
                while node is not None and type(node) == FirstChanceNode:
                    node._remove_partial_matches(partial_match_to_remove)
                    node = node._parent

    def get_first_FCNodes(self):
        if self.is_first:
            return [self]
        else:
            return []


class PostProcessingNode(InternalNegationNode):
    """
    An internal node connects two subtrees, i.e., two subpatterns of the evaluated pattern.
    """

    def __init__(self, sliding_window: timedelta, is_first: bool, is_last: bool, top_operator, parent: Node = None,
                 event_defs: List[Tuple[int, QItem]] = None,
                 left: Node = None, right: Node = None):
        super().__init__(sliding_window, is_first, is_last, top_operator, parent, event_defs, left, right)

    def handle_new_partial_match(self, partial_match_source: Node):

        if partial_match_source == self._left_subtree:
            other_subtree = self._right_subtree
            if self.is_last:
                new_partial_match = partial_match_source.get_last_unhandled_partial_match()
                self.waiting_for_time_out.append(new_partial_match)
                return

        elif partial_match_source == self._right_subtree:
            if self.is_last:
                self.handle_PM_with_negation_at_the_end(partial_match_source)
            return

        else:
            raise Exception()  # should never happen

        # we arrive here only if the new partial match is a positive event
        new_partial_match = partial_match_source.get_last_unhandled_partial_match()  # A1 et C1
        first_event_defs = partial_match_source.get_event_definitions()
        other_subtree.clean_expired_partial_matches(new_partial_match.last_timestamp)

        partial_matches_to_compare = other_subtree.get_partial_matches()  # B
        second_event_defs = other_subtree.get_event_definitions()
        self.clean_expired_partial_matches(new_partial_match.last_timestamp)

        for partialMatch in partial_matches_to_compare:
            # for every negative event, we want to check if it invalidates new_partial_match
            if self._try_create_new_match(new_partial_match, partialMatch, first_event_defs, second_event_defs):
                return

        self.add_partial_match(new_partial_match)
        if self._parent is not None:
            self._parent.handle_new_partial_match(self)


class Tree:
    """
    Represents an evaluation tree. Implements the functionality of constructing an actual tree from a "tree structure"
    object returned by a tree builder. Other than that, merely acts as a proxy to the tree root node.
    """

    def __init__(self, tree_structure: tuple, pattern: Pattern, eval_mechanisms_params):
        # Note that right now only "flat" sequence patterns and "flat" conjunction patterns are supported

        # We create a tree with only the positive event and the conditions that apply to them
        temp_root = Tree.__construct_tree(pattern.structure.get_top_operator() == SeqOperator,
                                          tree_structure, pattern.structure.args, pattern.window)
        temp_root.apply_formula(pattern.condition)

        self.__root = temp_root

        # According to the Negation Mode, we add the negative events in a different way
        negation_mode = eval_mechanisms_params.negation_mode
        if negation_mode == NegationMode.POST_PROCESSING:
            self.__root = self.create_PostProcessing_Tree(temp_root, pattern)
        elif negation_mode == NegationMode.FIRST_CHANCE:
            self.__root = self.create_FirstChanceNegation_Tree(pattern)
        else:
            raise Exception()  # should never happen

    def create_FirstChanceNegation_Tree(self, pattern: Pattern):

        top_operator = pattern.origin_structure.get_top_operator()

        negative_event_list = pattern.negative_event.get_args()
        # contains only not operators
        origin_event_list = pattern.origin_structure.get_args()
        # contains the original pattern with all operators

        # init node to use it out of the scope of the for
        node = self.__root
        for p in negative_event_list:
            keep_looking = True
            p_conditions = pattern.condition.get_events_in_a_condition_with(p.get_event_name())
            set_of_depending_events = set()
            if p_conditions is not None:
                p_conditions.get_all_terms(set_of_depending_events)
            if pattern.origin_structure.get_top_operator() == SeqOperator:
                find_positive_events_before(p, set_of_depending_events, pattern.origin_structure.get_args())
            if p.get_event_name() in set_of_depending_events:
                set_of_depending_events.remove(p.get_event_name())
            node = self.__root.get_deepest_leave()
            """
            set_of_depending_events : contains all events which have to appear "before" (==lower than) 
            the negative event p in the tree. We search the right place to add p in the tree: 
            we iterate on the tree from the leaf to the top until event_defs of the current node contains 
            the events of the set: that means that all the events in the set are in the subtree of this node
            """
            while keep_looking:
                names = {item[1].name for item in node.get_event_definitions()}
                result = all(elem in names for elem in set_of_depending_events)
                counter = 0
                if result:
                    while type(node._parent) == FirstChanceNode:
                        node = node._parent
                    if p == origin_event_list[counter]:
                        temporal_root = FirstChanceNode(pattern.window, is_first=True, is_last=False,
                                                        top_operator=top_operator)
                        counter += 1
                    elif len(negative_event_list) - negative_event_list.index(p) \
                            == len(origin_event_list) - origin_event_list.index(p):
                        temporal_root = FirstChanceNode(pattern.window, is_first=False, is_last=True,
                                                        top_operator=top_operator)
                    else:
                        temporal_root = FirstChanceNode(pattern.window, is_first=False, is_last=False,
                                                        top_operator=top_operator)

                    temp_neg_event = LeafNode(pattern.window, 1, p, temporal_root)
                    temp_neg_event.apply_formula(pattern.condition)
                    temporal_root.set_subtrees(node, temp_neg_event)
                    temp_neg_event.set_parent(temporal_root)
                    temporal_root.set_parent(node._parent)
                    node.set_parent(temporal_root)
                    if temporal_root._parent != None:
                        temporal_root._parent.set_subtrees(temporal_root, temporal_root._parent._right_subtree)

                    # apply_formula manually for negation node
                    names = {item[1].name for item in temporal_root._event_defs}
                    condition = pattern.condition.get_formula_of(names)
                    temporal_root._condition = condition if condition else TrueFormula()

                    keep_looking = False
                else:
                    node = node._parent

        self.__root = node.get_root()
        return self.__root

    def create_PostProcessing_Tree(self, temp_root: Node, pattern: Pattern):
        """
        We add the negative nodes at the end of the tree
        """
        top_operator = pattern.origin_structure.get_top_operator()
        negative_event_list = pattern.negative_event.get_args()
        # contains only not operators
        origin_event_list = pattern.origin_structure.get_args()
        # contains the original pattern with all operators

        counter = 0
        for p in negative_event_list:
            if p == origin_event_list[counter]:
                temporal_root = PostProcessingNode(pattern.window, is_first=True, is_last=False,
                                                   top_operator=top_operator)
                counter += 1
            elif len(negative_event_list) - negative_event_list.index(p) \
                    == len(origin_event_list) - origin_event_list.index(p):
                temporal_root = PostProcessingNode(pattern.window, is_first=False, is_last=True,
                                                   top_operator=top_operator)
            else:
                temporal_root = PostProcessingNode(pattern.window, is_first=False, is_last=False,
                                                   top_operator=top_operator)

            temp_neg_event = LeafNode(pattern.window, 1, p, temporal_root)
            temporal_root.set_subtrees(temp_root, temp_neg_event)
            temp_neg_event.set_parent(temporal_root)
            temp_root.set_parent(temporal_root)
            temp_root = temp_root._parent

            # apply_formula manually for negation nodes
            names = {item[1].name for item in temp_root._event_defs}
            condition = pattern.condition.get_formula_of(names)
            temp_root._condition = condition if condition else TrueFormula()

        self.__root = temp_root
        return self.__root

    def get_root(self):
        return self.__root

    def handle_EOF(self, matches: Stream):
        """
        We add as matches all the PMs for which there was a risk to be invalidated later.
        Now we finished the input stream so there is no more risk !
        """
        for match in self.__root.matches_to_handle_at_EOF:
            matches.add_item(PatternMatch(match.events))
        node = self.__root.get_first_last_negative_node()
        for match in node.waiting_for_time_out:
            matches.add_item(PatternMatch(match.events))

    def get_leaves(self):
        return self.__root.get_leaves()

    def get_matches(self):
        while self.__root.has_partial_matches():
            yield self.__root.consume_first_partial_match().events

    @staticmethod
    def __construct_tree(is_sequence: bool, tree_structure: tuple or int, args: List[QItem],
                         sliding_window: timedelta, parent: Node = None):
        if type(tree_structure) == int:
            return LeafNode(sliding_window, tree_structure, args[tree_structure], parent)
        current = SeqNode(sliding_window, parent) if is_sequence else AndNode(sliding_window, parent)
        left_structure, right_structure = tree_structure
        left = Tree.__construct_tree(is_sequence, left_structure, args, sliding_window, current)
        right = Tree.__construct_tree(is_sequence, right_structure, args, sliding_window, current)
        current.set_subtrees(left, right)
        return current


class TreeBasedEvaluationMechanism(EvaluationMechanism):
    """
    An implementation of the tree-based evaluation mechanism.
    """

    def __init__(self, pattern: Pattern, tree_structure: tuple, eval_mechanism_params):
        self.__tree = Tree(tree_structure, pattern, eval_mechanism_params)

    def eval(self, events: Stream, matches: Stream):
        event_types_listeners = {}
        # register leaf listeners for event types.
        for leaf in self.__tree.get_leaves():
            event_type = leaf.get_event_type()
            if event_type in event_types_listeners.keys():
                event_types_listeners[event_type].append(leaf)
            else:
                event_types_listeners[event_type] = [leaf]

        # Send events to listening leaves.
        for event in events:
            if event.event_type in event_types_listeners.keys():
                for leaf in event_types_listeners[event.event_type]:
                    leaf.handle_event(event)
                    for match in self.__tree.get_matches():
                        matches.add_item(PatternMatch(match))

        # Now that we finished the input stream, if there were some PMs risking to be invalidated by a negative event
        # at the end of the pattern, we handle them now
        if (type(self.__tree.get_root()) == PostProcessingNode or type(self.__tree.get_root()) == FirstChanceNode) \
                and self.__tree.get_root().is_last:
            self.__tree.handle_EOF(matches)

        matches.close()
