"""
Judge pipeline for evaluating and optionally rewriting CYOA turns.

Each JudgeStep has three phases:
1. Classifier: Evaluates single turn - "Does this need fixing?" (optional)
2. Rewriter: Generates corrected turn using full context
3. Comparator (Judge): Compares original vs rewrite - "Is rewrite better?"

The pipeline supports iterative retries if the comparator rejects the rewrite.
"""
from typing import Dict, Any, List
from .llm_router import call_llm


def _parse_boolean_response(text: str, default: bool = False) -> bool:
    """Parse YES/NO response from LLM, handling variations."""
    if not text:
        return default
    upper = text.strip().upper()
    # Check for positive indicators
    if any(x in upper for x in ['YES', 'TRUE', 'PASS']):
        return True
    # Check for negative indicators  
    if any(x in upper for x in ['NO', 'FALSE', 'FAIL']):
        return False
    return default


def _build_context_messages(messages: List[Dict], turn_text: str, use_full_context: bool) -> List[Dict]:
    """
    Build message context for LLM call.
    
    Args:
        messages: Full message history
        turn_text: The current turn text
        use_full_context: If True, use full messages; if False, just turn text
    
    Returns:
        List of message dicts for LLM
    """
    if use_full_context:
        return list(messages)
    else:
        return [{'role': 'user', 'content': turn_text}]


def run_judge_pipeline(messages, story_turn: str, config) -> Dict[str, Any]:
    """
    Run configured judge steps in order on a story turn.
    
    Each step:
    1. Optionally classifies if turn needs correction (skip if no classifier)
    2. If needed, rewrites the turn (with configurable retries)
    3. Compares original vs rewrite to decide which to use
    
    Args:
        messages: Full message history for context
        story_turn: The turn text to evaluate
        config: Configuration with judge_steps
    
    Returns:
        dict: {
            'final_turn': str - The final turn text after all steps
            'was_modified': bool - Whether any step modified the turn
            'steps': list - Details of each step execution
        }
    """
    result = {
        'final_turn': story_turn,
        'was_modified': False,
        'steps': []
    }

    if not config:
        return result

    judge_steps = config.judge_steps.filter(enabled=True).order_by('order', 'id')
    if not judge_steps.exists():
        return result

    current_turn = story_turn

    for step in judge_steps:
        step_result = {
            'step_id': step.id,
            'name': step.name,
            'classifier_response': '',
            'needs_correction': False,
            'attempts': [],
            'used_rewrite': False,
            'final_used': 'original',
            'error': None
        }

        try:
            # Phase 1: Classification (optional - skip to always rewrite)
            needs_correction = True  # Default: always try to rewrite
            
            if step.classifier_prompt and step.classifier_model:
                print(f"[JUDGE:{step.name}] Running classifier")
                classifier_messages = _build_context_messages(
                    messages, current_turn, step.classifier_use_full_context
                )
                classifier_content = f"{step.classifier_question}\n\n{current_turn}"
                classifier_messages = [{'role': 'user', 'content': classifier_content}]
                
                classifier_response = call_llm(
                    messages=classifier_messages,
                    system_prompt=step.classifier_prompt.prompt_text,
                    llm_model=step.classifier_model,
                    timeout=step.classifier_timeout,
                    disable_thinking=True
                )
                step_result['classifier_response'] = classifier_response
                needs_correction = _parse_boolean_response(classifier_response, default=True)
                step_result['needs_correction'] = needs_correction
                
                if not needs_correction:
                    print(f"[JUDGE:{step.name}] ✓ Classifier says no correction needed")
                    step_result['final_used'] = 'original'
                    result['steps'].append(step_result)
                    continue
                else:
                    print(f"[JUDGE:{step.name}] ⚠️  Classifier flagged for correction")
            
            # Phase 2 & 3: Rewrite and Compare (with retries)
            max_attempts = step.max_rewrite_attempts or 3
            rewrite_approved = False
            best_rewrite = None
            all_attempts_failed = False
            last_error = None
            
            for attempt_num in range(1, max_attempts + 1):
                print(f"[JUDGE:{step.name}] Rewrite attempt {attempt_num}/{max_attempts}")
                
                attempt_result = {
                    'attempt_number': attempt_num,
                    'rewrite_text': '',
                    'compare_response': '',
                    'approved': False
                }
                
                try:
                    # Generate rewrite
                    if step.rewrite_use_full_context:
                        rewrite_messages = list(messages) + [{
                            'role': 'user',
                            'content': f"{step.rewrite_instruction}\n\nTURN TO FIX:\n{current_turn}"
                        }]
                    else:
                        rewrite_messages = [{
                            'role': 'user',
                            'content': f"{step.rewrite_instruction}\n\nTURN TO FIX:\n{current_turn}"
                        }]
                    
                    rewrite_text = call_llm(
                        messages=rewrite_messages,
                        system_prompt=step.rewrite_prompt.prompt_text,
                        llm_model=step.rewrite_model,
                        timeout=step.rewrite_timeout
                    )
                    attempt_result['rewrite_text'] = rewrite_text
                    
                    # Compare original vs rewrite
                    compare_content = (
                        f"{step.compare_question}\n\n"
                        f"ORIGINAL:\n{current_turn}\n\n"
                        f"CORRECTED:\n{rewrite_text}"
                    )
                    compare_response = call_llm(
                        messages=[{'role': 'user', 'content': compare_content}],
                        system_prompt=step.compare_prompt.prompt_text,
                        llm_model=step.compare_model,
                        timeout=step.compare_timeout,
                        disable_thinking=True
                    )
                    attempt_result['compare_response'] = compare_response
                    approved = _parse_boolean_response(compare_response, default=False)
                    attempt_result['approved'] = approved
                    
                    if approved:
                        print(f"[JUDGE:{step.name}] ✅ Rewrite approved on attempt {attempt_num}")
                        best_rewrite = rewrite_text
                        rewrite_approved = True
                        step_result['attempts'].append(attempt_result)
                        break
                    else:
                        print(f"[JUDGE:{step.name}] ✗ Rewrite rejected by comparator")
                
                except Exception as e:
                    print(f"[JUDGE:{step.name}] Error in attempt {attempt_num}: {e}")
                    attempt_result['error'] = str(e)
                    last_error = str(e)
                    all_attempts_failed = True
                
                step_result['attempts'].append(attempt_result)
            
            # If all attempts failed with errors, record the error
            if all_attempts_failed and not rewrite_approved and last_error:
                step_result['error'] = last_error
            
            # Use rewrite if approved, otherwise keep original
            if rewrite_approved and best_rewrite:
                current_turn = best_rewrite
                step_result['used_rewrite'] = True
                step_result['final_used'] = 'rewrite'
                result['was_modified'] = True
                print(f"[JUDGE:{step.name}] Using rewritten turn")
            else:
                step_result['final_used'] = 'original'
                print(f"[JUDGE:{step.name}] All attempts failed, keeping original")
            
            result['steps'].append(step_result)

        except Exception as exc:
            print(f"[JUDGE:{step.name}] Step error: {exc}")
            step_result['error'] = str(exc)
            step_result['final_used'] = 'original'
            result['steps'].append(step_result)

    result['final_turn'] = current_turn
    return result
