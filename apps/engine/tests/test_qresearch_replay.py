from copy import deepcopy

import pytest

from qresearch.replay import verify_result


def test_replay_reports_only_bounded_fitting_roundoff():
    saved = {'fits': [{'means': [[0.25]], 'converged': True,
                       'cointegration': {'eligible': True, 'p_value': 0.001}}],
             'results': {'HMM allocation': {'regimes': [{'trend': 0.8, 'regime': 'trend'}],
                                            'equity': [{'equity': 100000.0}],
                                            'trades': [{'quantity': 4}]}}}
    actual = deepcopy(saved)
    actual['fits'][0]['means'][0][0] += 2e-12
    actual['results']['HMM allocation']['regimes'][0]['trend'] += 1e-12
    result = verify_result(actual, saved, 'hmm-multi-strategy')
    assert not result['exact'] and result['tolerated_fitted_values'] == 2
    assert 1e-12 < result['maximum_fitted_absolute_difference'] < 3e-12
    assert verify_result(saved, saved, 'hmm-multi-strategy')['exact']
    with pytest.raises(ValueError): verify_result(actual, saved, 'basket-walk-forward')

    # A financially tiny ledger difference is still a failure, as are changed
    # regimes, integer trade decisions, convergence and statistical gates.
    changes = [
        lambda x: x['results']['HMM allocation']['equity'][0].update(equity=100000.00000001),
        lambda x: x['results']['HMM allocation']['trades'][0].update(quantity=5),
        lambda x: x['results']['HMM allocation']['regimes'][0].update(regime='range'),
        lambda x: x['fits'][0].update(converged=False),
        lambda x: x['fits'][0]['cointegration'].update(eligible=False),
        lambda x: x['fits'][0].update(means=[[0.25000001]]),
        lambda x: x['fits'][0].update(means=[[float('nan')]]),
        lambda x: x['fits'].append(x['fits'][0]),
    ]
    for change in changes:
        altered = deepcopy(saved)
        change(altered)
        with pytest.raises(ValueError): verify_result(altered, saved, 'hmm-multi-strategy')
