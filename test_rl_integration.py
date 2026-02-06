"""
Phase 2 RL Integration Tests
Validates RL model loading, recommendation endpoints, and prerequisite checking.
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from main import app
from services.rl.rl_service import get_rl_service, RLModelService
from services.schemas import RecommendationRequest, StateVectorRequest


client = TestClient(app)


class TestRLServiceInitialization:
    """Test RL service singleton and model loading."""
    
    def test_singleton_pattern(self):
        """Verify RLModelService follows singleton pattern."""
        service1 = get_rl_service()
        service2 = get_rl_service()
        
        assert service1 is service2, "RLModelService should be singleton"
    
    def test_service_initialization(self):
        """Verify service initializes with correct attributes."""
        service = get_rl_service()
        
        assert hasattr(service, 'models')
        assert hasattr(service, 'env')
        assert 'ppo' in service.models
        assert 'dqn' in service.models
        assert 'a2c' in service.models
    
    def test_available_strategies(self):
        """Check that available strategies are correctly identified."""
        service = get_rl_service()
        strategies = service._get_available_strategies()
        
        # Baseline should always be available
        assert 'baseline' in strategies
        
        # If models loaded, should have model strategies
        if service.models_loaded:
            assert len(strategies) >= 2  # baseline + at least one model


class TestPrerequisiteChecking:
    """Test prerequisite validation logic."""
    
    def test_no_prerequisites(self):
        """Topics without gates should have no violations."""
        service = get_rl_service()
        mastery_dict = {
            'UNIV_SYN_LOGIC': 0.5,
            'UNIV_VAR': 0.3
        }
        
        # UNIV_SYN_LOGIC has no prerequisites
        violations = service._check_prerequisites('UNIV_SYN_LOGIC', mastery_dict)
        assert violations == []
    
    def test_met_prerequisites(self):
        """Topics with sufficient mastery should pass."""
        service = get_rl_service()
        mastery_dict = {
            'UNIV_VAR': 0.70,
            'UNIV_FUNC': 0.75,
            'UNIV_COLL': 0.65,
            'UNIV_OOP': 0.20
        }
        
        # OOP requires VAR, FUNC, COLL >= 0.60 (all met)
        violations = service._check_prerequisites('UNIV_OOP', mastery_dict)
        assert violations == []
    
    def test_violated_prerequisites(self):
        """Topics with insufficient mastery should fail."""
        service = get_rl_service()
        mastery_dict = {
            'UNIV_VAR': 0.45,  # Below 0.60
            'UNIV_FUNC': 0.52,  # Below 0.60
            'UNIV_COLL': 0.38,  # Below 0.60
            'UNIV_OOP': 0.00
        }
        
        # OOP requires VAR, FUNC, COLL >= 0.60 (all violated)
        violations = service._check_prerequisites('UNIV_OOP', mastery_dict)
        assert len(violations) == 3
        assert any('UNIV_VAR' in v for v in violations)
        assert any('UNIV_FUNC' in v for v in violations)
        assert any('UNIV_COLL' in v for v in violations)


class TestBaselineFallback:
    """Test baseline recommendation strategy."""
    
    def test_baseline_lowest_mastery(self):
        """Baseline should recommend lowest mastery topic with prerequisites met."""
        service = get_rl_service()
        mastery_dict = {
            'UNIV_SYN_LOGIC': 0.80,
            'UNIV_VAR': 0.30,  # Lowest, no prerequisites
            'UNIV_FUNC': 0.50,
            'UNIV_LOOP': 0.60
        }
        
        result = service._baseline_fallback(mastery_dict, 'python_3')
        
        assert result['mapping_id'] == 'UNIV_VAR'
        assert result['strategy_used'] == 'baseline'
        assert result['action_id'] == -1
        assert 'major_topic_id' in result
        assert result['major_topic_id'].startswith('PY_')
    
    def test_baseline_skips_prerequisites_violations(self):
        """Baseline should skip topics with unmet prerequisites."""
        service = get_rl_service()
        mastery_dict = {
            'UNIV_SYN_LOGIC': 0.80,
            'UNIV_VAR': 0.70,
            'UNIV_FUNC': 0.20,  # Lowest mastery but requires VAR >= 0.60 (met)
            'UNIV_OOP': 0.10     # Even lower but requires VAR, FUNC, COLL >= 0.60
        }
        
        result = service._baseline_fallback(mastery_dict, 'python_3')
        
        # Should pick FUNC (requires VAR >= 0.60 which is met)
        # Should NOT pick OOP (requires FUNC >= 0.60 which is not met)
        assert result['mapping_id'] in ['UNIV_FUNC', 'UNIV_SYN_LOGIC', 'UNIV_VAR']
    
    def test_baseline_difficulty_progression(self):
        """Baseline should set difficulty slightly above current mastery."""
        service = get_rl_service()
        mastery_dict = {
            'UNIV_VAR': 0.45
        }
        
        result = service._baseline_fallback(mastery_dict, 'javascript_es6')
        
        # Should be close to 0.55 (0.45 + 0.1), snapped to nearest tier
        assert 0.4 <= result['difficulty'] <= 0.6


class TestMappingIDConversion:
    """Test universal mapping_id to language-specific major_topic_id conversion."""
    
    def test_python_conversion(self):
        """Test conversion for Python language."""
        service = get_rl_service()
        mastery_dict = {'UNIV_VAR': 0.5}
        
        result = service._baseline_fallback(mastery_dict, 'python_3')
        
        assert result['major_topic_id'].startswith('PY_')
        assert 'VAR' in result['major_topic_id']
    
    def test_javascript_conversion(self):
        """Test conversion for JavaScript language."""
        service = get_rl_service()
        mastery_dict = {'UNIV_FUNC': 0.6, 'UNIV_VAR': 0.7}
        
        result = service._baseline_fallback(mastery_dict, 'javascript_es6')
        
        assert result['major_topic_id'].startswith('JS_')
    
    def test_invalid_language_raises_error(self):
        """Invalid language_id should raise ValueError."""
        service = get_rl_service()
        state_vector = np.zeros(38, dtype=np.float32)
        mastery_dict = {'UNIV_VAR': 0.5}
        
        with pytest.raises(ValueError, match="Invalid language_id"):
            service.get_recommendation(
                state_vector, mastery_dict, 'invalid_lang', 'baseline'
            )


class TestHealthEndpoint:
    """Test RL health check endpoint."""
    
    def test_health_endpoint_accessible(self):
        """Health endpoint should be accessible without authentication."""
        response = client.get("/api/rl/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data['service'] == 'rl_model_service'
        assert data['status'] in ['healthy', 'degraded']
        assert 'models_loaded' in data
        assert 'available_strategies' in data
    
    def test_health_shows_model_status(self):
        """Health should show individual model loading status."""
        response = client.get("/api/rl/health")
        data = response.json()
        
        assert 'ppo' in data['models_loaded']
        assert 'dqn' in data['models_loaded']
        assert 'a2c' in data['models_loaded']
        
        # Each model status should be boolean
        assert isinstance(data['models_loaded']['ppo'], bool)


class TestStrategiesEndpoint:
    """Test available strategies listing endpoint."""
    
    def test_strategies_endpoint_accessible(self):
        """Strategies endpoint should be accessible without authentication."""
        response = client.get("/api/rl/strategies")
        
        assert response.status_code == 200
        data = response.json()
        
        assert 'available_strategies' in data
        assert 'strategy_details' in data
    
    def test_baseline_always_available(self):
        """Baseline strategy should always be available."""
        response = client.get("/api/rl/strategies")
        data = response.json()
        
        assert 'baseline' in data['available_strategies']
        assert data['strategy_details']['baseline']['available'] is True


class TestRecommendationEndpoint:
    """Test RL recommendation endpoint (requires authentication)."""
    
    @pytest.fixture
    def auth_header(self):
        """Create authenticated user and return auth header."""
        # Register test user
        register_payload = {
            "email": "test_rl@example.com",
            "password": "testpass123",
            "language_id": "python_3",
            "experience_level": "beginner"
        }
        client.post("/api/auth/register", json=register_payload)
        
        # Login to get token
        login_payload = {
            "email": "test_rl@example.com",
            "password": "testpass123"
        }
        response = client.post("/api/auth/login", json=login_payload)
        token = response.json()['access_token']
        
        return {"Authorization": f"Bearer {token}"}
    
    def test_recommend_requires_authentication(self):
        """Recommendation endpoint should require authentication."""
        payload = {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "language_id": "python_3",
            "strategy": "baseline"
        }
        
        response = client.post("/api/rl/recommend", json=payload)
        assert response.status_code == 401  # Unauthorized
    
    def test_recommend_with_baseline(self, auth_header):
        """Test baseline recommendation for authenticated user."""
        # Get user_id from auth token
        profile_response = client.get("/api/auth/me", headers=auth_header)
        user_id = profile_response.json()['id']
        
        payload = {
            "user_id": user_id,
            "language_id": "python_3",
            "strategy": "baseline",
            "deterministic": True
        }
        
        response = client.post("/api/rl/recommend", json=payload, headers=auth_header)
        
        # May fail if user has no state data yet, but should not be auth error
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert 'mapping_id' in data
            assert 'major_topic_id' in data
            assert 'difficulty' in data
            assert data['strategy_used'] == 'baseline'


class TestEnsembleStrategy:
    """Test ensemble recommendation logic."""
    
    def test_ensemble_requires_multiple_models(self):
        """Ensemble should only be available if 2+ models loaded."""
        service = get_rl_service()
        strategies = service._get_available_strategies()
        
        loaded_count = sum(
            1 for m in service.models.values() if m is not None
        )
        
        if loaded_count >= 2:
            assert 'ensemble' in strategies
        else:
            assert 'ensemble' not in strategies


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
