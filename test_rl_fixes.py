"""
Test script to verify all three RL fixes are working correctly.

Run this before retraining to confirm:
1. High-velocity learner detection
2. Error remediation bonuses
3. Cross-language transfer

Expected: All tests pass with realistic values
"""

from services.rl.student_simulator import StudentSimulator
import numpy as np

def test_high_velocity_detection():
    """Test FIX #1: High-velocity learner detection."""
    print("=" * 70)
    print("TEST 1: High-Velocity Learner Detection")
    print("=" * 70)
    
    sim = StudentSimulator(seed=42)
    profile = sim.profiles[50]  # Average learner
    
    # Normal learning
    normal_mastery = sim.calculate_mastery_update(
        profile,
        old_mastery=0.5,
        exam_accuracy=0.75,
        difficulty=0.6,
        fluency_ratio=1.0  # Normal speed
    )
    
    # High-velocity learning (accuracy >90%, fluency >1.2, difficulty >0.6)
    high_vel_mastery = sim.calculate_mastery_update(
        profile,
        old_mastery=0.5,
        exam_accuracy=0.95,  # Excellent performance
        difficulty=0.7,       # Hard difficulty
        fluency_ratio=1.5     # Fast completion
    )
    
    print(f"Normal learning:      0.50 → {normal_mastery:.3f}")
    print(f"High-velocity learning: 0.50 → {high_vel_mastery:.3f}")
    print(f"Difference: +{(high_vel_mastery - normal_mastery):.3f}")
    
    if high_vel_mastery > normal_mastery:
        print("✅ PASS: High-velocity students learn faster!")
    else:
        print("❌ FAIL: High-velocity detection not working")
    
    print()


def test_error_remediation():
    """Test FIX #2: Error remediation bonuses."""
    print("=" * 70)
    print("TEST 2: Error Remediation Bonuses")
    print("=" * 70)
    
    sim = StudentSimulator(seed=42)
    profile = sim.profiles[0]
    
    # Simulate student making an error
    error_type = sim.generate_error_type('UNIV_VAR', is_correct=False, difficulty=0.7)
    print(f"Generated error for UNIV_VAR: {error_type}")
    
    # Track the error
    profile.recent_errors.append(error_type)
    print(f"Student's recent errors: {profile.recent_errors}")
    
    # Student fixes the error
    bonus = sim.calculate_remediation_bonus(
        profile,
        topic='UNIV_VAR',
        is_correct=True,
        error_type=None
    )
    
    print(f"Remediation bonus: +{bonus:.3f}")
    print(f"Errors after fixing: {profile.recent_errors}")
    
    if bonus > 0:
        print("✅ PASS: Students get bonus for fixing errors!")
    else:
        print("❌ FAIL: Error remediation not working")
    
    print()


def test_cross_language_transfer():
    """Test FIX #3: Cross-language transfer."""
    print("=" * 70)
    print("TEST 3: Cross-Language Transfer")
    print("=" * 70)
    
    sim = StudentSimulator(seed=42)
    
    # Student knows Python well
    python_mastery = {
        'UNIV_VAR': 0.80,
        'UNIV_FUNC': 0.75,
        'UNIV_LOOP': 0.70,
        'UNIV_COND': 0.65,
        'UNIV_SYN_LOGIC': 0.50,
        'UNIV_SYN_PREC': 0.50,
        'UNIV_COLL': 0.40,
        'UNIV_OOP': 0.35
    }
    
    print("Python mastery:")
    for topic, score in list(python_mastery.items())[:4]:
        print(f"  {topic}: {score:.2f}")
    
    # Transfer to JavaScript
    js_mastery = sim.calculate_cross_language_boost(
        source_language='python_3',
        target_language='javascript_es6',
        source_mastery=python_mastery
    )
    
    print("\nJavaScript mastery (after transfer):")
    for topic in ['UNIV_VAR', 'UNIV_FUNC', 'UNIV_LOOP', 'UNIV_COND']:
        transferred = js_mastery[topic]
        original = python_mastery[topic]
        print(f"  {topic}: {original:.2f} → {transferred:.2f} ({transferred/original*100:.0f}%)")
    
    # Check if transfer happened
    avg_transfer = np.mean([js_mastery[t] for t in python_mastery.keys() if python_mastery[t] > 0.3])
    
    if avg_transfer > 0.3:
        print(f"\n✅ PASS: Transfer working! Avg transferred mastery: {avg_transfer:.2f}")
    else:
        print(f"\n❌ FAIL: No transfer detected. Avg mastery: {avg_transfer:.2f}")
    
    print()


def test_all_fixes_loaded():
    """Verify all components loaded correctly."""
    print("=" * 70)
    print("INITIALIZATION CHECK")
    print("=" * 70)
    
    sim = StudentSimulator(seed=42)
    
    print(f"✅ Student profiles: {len(sim.profiles)}")
    print(f"✅ Error categories: {len(sim.error_taxonomy)}")
    print(f"✅ Cross-language transfers: {len(sim.cross_lang_transfer)}")
    print(f"✅ Languages: {sorted(sim.languages)}")
    
    # Check error taxonomy
    print(f"\nError categories loaded:")
    for mapping_id, patterns in list(sim.error_taxonomy.items())[:3]:
        print(f"  {mapping_id}: {len(patterns)} error types")
    
    # Check cross-language transfers
    print(f"\nCross-language transfers loaded:")
    sample_transfers = list(sim.cross_lang_transfer.keys())[:3]
    for transfer_key in sample_transfers:
        coeffs = sim.cross_lang_transfer[transfer_key]
        print(f"  {transfer_key}: {coeffs['logic_accel']:.2f} accel, {coeffs['syntax_friction']:+.2f} friction")
    
    print()


if __name__ == "__main__":
    print("\n")
    print("🔍 " + "=" * 68)
    print("   RL FIXES VERIFICATION TEST")
    print("=" * 70)
    print()
    
    # Run all tests
    test_all_fixes_loaded()
    test_high_velocity_detection()
    test_error_remediation()
    test_cross_language_transfer()
    
    print("=" * 70)
    print("✅ ALL TESTS COMPLETE")
    print("=" * 70)
    print()
    print("Next step: Retrain models with:")
    print("  python train_rl_model.py --algorithm ppo --timesteps 100000")
    print("  python train_rl_model.py --algorithm dqn --timesteps 100000")
    print("  python train_rl_model.py --algorithm a2c --timesteps 100000")
    print()
