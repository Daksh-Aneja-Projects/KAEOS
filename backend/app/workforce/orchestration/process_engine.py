"""
KAEOS Workforce Layer — Process Engine

Executes BusinessProcess DAGs. Handles agent actions, human checkpoints,
and fairness gates. Updates ProcessExecution state.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.workforce.models.runtime import ProcessExecution, ProcessExecutionStatus
from app.workforce.models.core import BusinessProcess

logger = logging.getLogger(__name__)


class ProcessEngine:
    
    @staticmethod
    async def start_process(db: AsyncSession, process_slug: str, tenant_id: str, input_context: dict) -> ProcessExecution:
        """Starts a new execution of a business process."""
        q = await db.execute(
            select(BusinessProcess)
            .where(BusinessProcess.tenant_id == tenant_id)
            .where(BusinessProcess.slug == process_slug)
        )
        process = q.scalar_one_or_none()
        
        if not process:
            raise ValueError(f"Process {process_slug} not found")
            
        execution = ProcessExecution(
            tenant_id=tenant_id,
            process_id=process.id,
            department_id=process.department_id,
            status=ProcessExecutionStatus.RUNNING,
            total_steps=len(process.steps),
            context=input_context
        )
        
        # Set first step
        if process.steps:
            execution.current_step = process.steps[0]["id"]
            
        db.add(execution)
        
        # Update metrics on process
        process.execution_count += 1
        process.last_executed_at = datetime.now(timezone.utc)
        db.add(process)
        
        await db.commit()
        await db.refresh(execution)
        
        logger.info(f"Started process execution {execution.id} for {process_slug}")
        
        # In full implementation, this would queue a background task to process the step
        
        return execution
        
    @staticmethod
    async def advance_step(db: AsyncSession, execution_id: str, step_result: dict) -> ProcessExecution:
        """Advances an execution to the next step based on the result of the current one."""
        q = await db.execute(select(ProcessExecution).where(ProcessExecution.id == execution_id))
        execution = q.scalar_one_or_none()
        
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")
            
        if execution.status != ProcessExecutionStatus.RUNNING:
            logger.warning(f"Cannot advance execution {execution_id} in state {execution.status}")
            return execution
            
        # Update context
        ctx = dict(execution.context)
        ctx[execution.current_step] = step_result
        execution.context = ctx
        execution.steps_completed += 1
        
        # Fetch process definition
        p_q = await db.execute(select(BusinessProcess).where(BusinessProcess.id == execution.process_id))
        process = p_q.scalar_one()
        
        # Find next step (simplified: just sequential for now)
        current_idx = next((i for i, s in enumerate(process.steps) if s["id"] == execution.current_step), -1)
        
        if current_idx >= 0 and current_idx + 1 < len(process.steps):
            execution.current_step = process.steps[current_idx + 1]["id"]
        else:
            # Done
            execution.status = ProcessExecutionStatus.COMPLETED
            execution.completed_at = datetime.now(timezone.utc)
            execution.duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
            execution.result = step_result
            
        db.add(execution)
        await db.commit()
        
        return execution
