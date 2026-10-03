// IntentOS blast-radius policy (Cedar, https://www.cedarpolicy.com).
//
// Every agent Lambda asks this policy "may Raksha run this tool right now?" before doing anything.
// Cedar denies by default: a tool runs only if some permit matches and no forbid matches.
//
// resource.zone          fixed zone of the tool, from the tool registry (never from the LLM)
// resource.moves_money   true for tools that spend or request money
// context.effective_zone zone after the confidence floor (an unclear Zone 1 task becomes 2)
// context.approved       a caregiver approval was recorded for this task
// context.amount_inr     rupee amount in the arguments (0 if none)

// Zones 0-1: internal, read-only or conversational. Safe to run on their own.
@id("autonomous-when-safe-and-clear")
permit (principal, action == Raksha::Action::"RunTool", resource)
when { resource.zone <= 1 && context.effective_zone <= 1 };

// Zone 2, or anything the planner wasn't sure about: only after a human says yes.
@id("human-gated-after-approval")
permit (principal, action == Raksha::Action::"RunTool", resource)
when { resource.zone <= 2 && context.approved };

// Zone 3: scams and emergencies alert the family immediately. Delay is the risk here.
@id("panic-override")
permit (principal, action == Raksha::Action::"RunTool", resource)
when { resource.zone == 3 };

// Money never moves on the model's say-so, whatever else matched.
@id("money-needs-approval")
forbid (principal, action == Raksha::Action::"RunTool", resource)
when { resource.moves_money && !context.approved };

// Demo spending cap, even with approval.
@id("demo-spending-cap")
forbid (principal, action == Raksha::Action::"RunTool", resource)
when { resource.moves_money && context.amount_inr > 5000 };
