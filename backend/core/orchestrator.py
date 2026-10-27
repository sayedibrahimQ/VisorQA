"""
VisorQA FSM Orchestrator - (Finite State Machine & 3-Strike Self-Healing Loop)
Executes the 5 autonomous nodes: SENSE -> TRIAGE -> DIAGNOSE -> PATCH -> VERIFY
"""

from typing import Optional, Callable, Awaitable
from backend.core.state import AgentState, FSMStep, RunStatus, SelfHealingAttempt
from backend.config import settings


class VisorOrchestrator:
    """
    Finite State Machine (FSM) controlling autonomous visual regression inspection
    and the 3-strike self-healing verification cycle.
    """

    def __init__(self, on_state_change: Optional[Callable[[AgentState], Awaitable[None]]] = None):
        self.on_state_change = on_state_change

    async def emit_update(self, state: AgentState) -> None:
        """Broadcast state updates to WebSocket observers"""
        if self.on_state_change:
            await self.on_state_change(state)

    async def step_1_sense(self, state: AgentState) -> AgentState:
        """
        Step 1: SENSE
        Boot sandbox, extract DOM Bounding Boxes (B_DOM), run SAM 3.1 masks (M_SAM),
        and identify visual discrepancies using vision_math equations.
        """
        state.transition_to(FSMStep.SENSE, RunStatus.RUNNING)
        await self.emit_update(state)
        # Interface stub: Logic to be wired to SandboxRunner & SAMClient
        return state

    async def step_2_triage(self, state: AgentState) -> AgentState:
        """
        Step 2: TRIAGE
        Map visual discrepancies to source tree using Muse Spark.
        Calculates Lowest Common Ancestor (LCA) in DOM hierarchy.
        """
        state.transition_to(FSMStep.TRIAGE)
        await self.emit_update(state)
        # Interface stub: Logic to be wired to MuseSparkClient
        return state

    async def step_3_diagnose(self, state: AgentState) -> AgentState:
        """
        Step 3: DIAGNOSE
        Multi-modal reasoning using Muse Wonder.
        Pinpoints exact CSS root cause (e.g. z-index collision, flex-wrap overflow).
        """
        state.transition_to(FSMStep.DIAGNOSE)
        await self.emit_update(state)
        # Interface stub: Logic to be wired to MuseWonderClient
        return state

    async def step_4_patch(self, state: AgentState) -> AgentState:
        """
        Step 4: PATCH
        Generate surgical CSS/React patch using Muse Code and apply via HMR.
        """
        state.transition_to(FSMStep.PATCH)
        await self.emit_update(state)
        # Interface stub: Logic to be wired to MuseCodeClient & SandboxRunner
        return state

    async def step_5_verify(self, state: AgentState) -> AgentState:
        """
        Step 5: VERIFY
        Re-segment modified sandbox. Evaluate V_r >= 0.85 and IoU = 0.
        Manages the 3-Strike Self-Healing Loop.
        """
        state.transition_to(FSMStep.VERIFY)
        await self.emit_update(state)
        # Interface stub: Logic to verify patch and manage strikes (max 3)
        return state

    async def execute_run(self, state: AgentState) -> AgentState:
        """
        Executes full FSM pipeline with 3-Strike Self-Healing loop
        """
        state = await self.step_1_sense(state)
        if not state.anomalies:
            state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
            await self.emit_update(state)
            return state

        # 3-Strike Self-Healing Loop
        while state.strike_count < settings.MAX_ATTEMPTS:
            state = await self.step_2_triage(state)
            state = await self.step_3_diagnose(state)
            state = await self.step_4_patch(state)
            state = await self.step_5_verify(state)

            # Check if verified
            latest_attempt = state.attempts[-1] if state.attempts else None
            if latest_attempt and latest_attempt.passed:
                state.transition_to(FSMStep.VERIFY, RunStatus.RESOLVED)
                await self.emit_update(state)
                return state

        # Exceeded max strikes
        state.transition_to(FSMStep.VERIFY, RunStatus.FAILED)
        await self.emit_update(state)
        return state
