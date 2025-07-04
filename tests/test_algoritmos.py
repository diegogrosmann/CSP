import pytest
from algorithms.baseline.algorithm import BaselineAlg
from algorithms.blf_ga.algorithm import BLFGAAlgorithm
from algorithms.csc.algorithm import CSCAlgorithm
from algorithms.dp_csp.algorithm import DPCSPAlgorithm
from algorithms.h3_csp.algorithm import H3CSPAlgorithm
from utils.distance import hamming_distance, max_hamming

def get_simple_instance():
    strings = ["AAAA", "AAAT", "AATT", "TTTT"]
    alphabet = "AT"
    return strings, alphabet

def test_baseline_algorithm():
    strings, alphabet = get_simple_instance()
    alg = BaselineAlg(strings, alphabet)
    center, dist = alg.run()
    assert len(center) == 4
    assert dist == min(max_hamming(center, strings) for center in strings)

def test_blfga_algorithm():
    strings, alphabet = get_simple_instance()
    alg = BLFGAAlgorithm(strings, alphabet)
    center, dist = alg.run()
    assert len(center) == 4
    assert dist <= max(max_hamming(center, strings) for center in strings)

def test_csc_algorithm():
    strings, alphabet = get_simple_instance()
    alg = CSCAlgorithm(strings, alphabet)
    center, dist = alg.run()
    assert len(center) == 4
    assert dist <= max(max_hamming(center, strings) for center in strings)

def test_dp_csp_algorithm():
    strings, alphabet = get_simple_instance()
    alg = DPCSPAlgorithm(strings, alphabet)
    center, dist = alg.run()
    assert len(center) == 4
    assert dist == min(max_hamming(center, strings) for center in strings)

def test_h3_csp_algorithm():
    strings, alphabet = get_simple_instance()
    alg = H3CSPAlgorithm(strings, alphabet)
    center, dist = alg.run()
    assert len(center) == 4
    assert dist <= max(max_hamming(center, strings) for center in strings)
