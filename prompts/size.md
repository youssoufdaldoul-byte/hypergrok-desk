<!-- SIZE seat. No judgement, no key. -->
SIZE   1. ticket = kelly(edge) * bank, clamped at 6% of the book. Free cash only,
          never the locked bag.
       2. ticket *= size_factor from the pick. dark data cuts to 0.40, a missing X
          account cuts to 0.60, both stack. (size_factor ALREADY carries these cuts:
          multiply by size_factor once, never apply 0.40 or 0.60 a second time.)
       3. ticket = min(ticket, liquidity_usd * 0.02). If you are more than 2% of the
          pool you are the exit, not a participant.
       4. if ticket < fee floor viable size -> return 0 and log it. Never size below
          what pays its own fees.
       Not exitable inside the slippage budget means the size is wrong, whatever the
       pick confidence said.
