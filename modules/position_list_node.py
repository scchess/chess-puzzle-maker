import os
import logging
from collections import namedtuple

import chess

from modules.bcolors import bcolors
from modules.candidate_moves import ambiguous
from modules.analysis import engine
from modules.utils import material_difference, material_count, fullmove_string


Analysis = namedtuple("Analysis", ["move_uci", "move_san", "evaluation"])

class PositionListNode(object):
    """ Linked list node of positions within a puzzle
    """
    def __init__(self, position, player_turn=True, best_move=None, evaluation=None, strict=True):
        self.position = position.copy()
        self.info_handler = engine.info_handlers[0]
        self.player_turn = player_turn
        self.best_move = best_move
        self.evaluation = evaluation
        self.next_position = None  # PositionListNode
        self.candidate_moves = []
        self.strict = strict

    def move_list(self):
        """ Returns a list of UCI moves starting from this position list node
        """
        if self.next_position is None or self.next_position.ambiguous() or self.next_position.position.is_game_over():
            if self.best_move is not None:
                return [self.best_move.bestmove.uci()]
            else:
                return []
        else:
            return [self.best_move.bestmove.uci()] + self.next_position.move_list()

    def category(self):
        if self.next_position is None:
            if self.position.is_game_over():
                return 'Mate'
            else:
                return 'Material'
        else:
            return self.next_position.category()

    def generate(self, depth):
        """ Generates the next position in the position list if the current
            position does not have an ambiguous next move
        """
        logging.debug(bcolors.WARNING + str(self.position) + bcolors.ENDC)
        logging.debug(bcolors.WARNING + self.position.fen() + bcolors.ENDC)
        logging.debug(bcolors.BLUE + ('Material difference:  %d' % self.material_difference()))
        logging.debug(bcolors.BLUE + ("# legal moves:        %d" % self.position.legal_moves.count()) + bcolors.ENDC)
        has_best = self.evaluate_best(depth)
        if not self.player_turn:
            self.next_position.generate(depth)
            return
        self.evaluate_candidate_moves(depth)
        if has_best and not self.ambiguous() and not self.game_over():
            logging.debug(bcolors.GREEN + "Going deeper...")
            self.next_position.generate(depth)
        else:
            log_str = "Not going deeper: "
            if self.ambiguous():
                log_str += "ambiguous"
            elif self.game_over():
                log_str += "game over"
            logging.debug(bcolors.WARNING + log_str + bcolors.ENDC)

    def evaluate_best(self, depth):
        logging.debug(bcolors.DIM + "Evaluating best move..." + bcolors.ENDC)
        engine.position(self.position)
        self.best_move = engine.go(depth=depth)
        if self.best_move.bestmove is not None:
            self.evaluation = self.info_handler.info["score"][1]
            self.next_position = PositionListNode(
                self.position.copy(),
                self.info_handler,
                not self.player_turn,
                strict = self.strict
            )
            self.next_position.position.push(self.best_move.bestmove)
            move = self.best_move.bestmove
            move_san = self.position.san(move)
            log_str = bcolors.GREEN
            log_str += ("%s%s (%s)" % (fullmove_string(self.position), move_san, move.uci())).ljust(22)
            if self.evaluation.mate:
                log_str += bcolors.BLUE + "   Mate: " + str(self.evaluation.mate)
            else:
                log_str += bcolors.BLUE + "   CP: " + str(self.evaluation.cp)
            logging.debug(log_str + bcolors.ENDC)
            return True
        else:
            logging.debug(bcolors.FAIL + "No best move!" + bcolors.ENDC)
            return False

    # Analyze the best possible moves from the current position
    def evaluate_candidate_moves(self, depth):
        multipv = min(3, self.position.legal_moves.count())
        if multipv == 0:
            return
        logging.debug(bcolors.DIM + ("Evaluating best %d moves..." % multipv) + bcolors.ENDC)
        engine.setoption({ "MultiPV": multipv })
        engine.position(self.position)
        engine.go(depth=depth)
        info = self.info_handler.info
        for i in range(multipv):
            move = info["pv"].get(i + 1)[0]
            move_uci = move.uci()
            move_san = self.position.san(move)
            evaluation = info["score"].get(i + 1)
            analysis = Analysis(move_uci, move_san, evaluation)
            log_str = bcolors.GREEN
            log_str += ("%s%s (%s)" % (fullmove_string(self.position), move_san, move_uci)).ljust(22)
            if evaluation.mate:
                log_str += bcolors.BLUE + "   Mate: " + str(evaluation.mate)
            else:
                log_str += bcolors.BLUE + "   CP: " + str(evaluation.cp)
            logging.debug(log_str + bcolors.ENDC)
            self.candidate_moves.append(analysis)
        engine.setoption({ "MultiPV": 1 })

    def material_difference(self):
        return material_difference(self.position)

    def is_complete(self, category, color, first_node, first_val):
        if self.next_position is not None:
            if ((category == 'Mate' and not self.ambiguous())
                or (category == 'Material' and self.next_position.next_position is not None)):
                return self.next_position.is_complete(category, color, False, first_val)

        # if the position was converted into a material advantage
        num_pieces = material_count(self.position)
        if category == 'Material':
            if color:
                if (self.material_difference() > 0.2 
                    and abs(self.material_difference() - first_val) > 0.1 
                    and first_val < 2
                    and self.evaluation.mate is None
                    and num_pieces > 6):
                    return True
                else:
                    return False
            else:
                if (self.material_difference() < -0.2 
                    and abs(self.material_difference() - first_val) > 0.1
                    and first_val > -2
                    and self.evaluation.mate is None
                    and num_pieces > 6):
                    return True
                else:
                    return False
        else:
            # mate puzzles are only complete at checkmate
            # return self.position.is_game_over() and num_pieces > 6:
            return self.position.is_game_over()

    def ambiguous(self):
        """ True if it's unclear whether there's a single best player move
        """
        return ambiguous([move.evaluation for move in self.candidate_moves])

    def game_over(self):
        return self.position.is_game_over() or self.next_position.position.is_game_over()
