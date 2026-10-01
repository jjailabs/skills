#!/usr/bin/ruby
# done-gate.rb — Stop hook
# Blocks the stop when the newest define-done report in <cwd>/.done/<task>/reports/
# says status: DONE but the contract files don't check out (revision, file hash,
# active_sha256, and a matching approval must all agree). Every other stop passes.
#
# Reversibility:
#   CLAUDE_DONE_GATE=0  -> disable instantly, no settings.json edit
#   remove the Stop entry from ~/.claude/settings.json -> permanent off
require "json"
require "yaml"
require "date"
require "digest"

exit 0 if ENV["CLAUDE_DONE_GATE"] == "0"

def load_yaml(path)
  YAML.safe_load(File.read(path), permitted_classes: [Date, Time])
rescue StandardError, Psych::Exception
  nil
end

input = JSON.parse($stdin.read) rescue exit(0)
exit 0 unless input.is_a?(Hash)
exit 0 if input["stop_hook_active"] # don't loop

done = File.join(input["cwd"] || Dir.pwd, ".done")
exit 0 unless File.directory?(done)

short = ->(h) { h.to_s[0, 12] }
problems = []
Dir.children(done).sort.each do |task|
  dir = File.join(done, task)
  reports = File.join(dir, "reports")
  next unless File.directory?(reports)
  files = Dir.children(reports).select { |f| f.end_with?(".yaml", ".yml") }.map { |f| File.join(reports, f) }
  next if files.empty?
  # ponytail: skill doesn't fix report names; mtime is the proxy. Upgrade = a timestamp field in the report once the skill defines one.
  report = load_yaml(files.max_by { |f| File.mtime(f) })
  next unless report.is_a?(Hash) && report["status"] == "DONE" # only DONE claims are gated

  active = load_yaml(File.join(dir, "active.yaml"))
  unless active.is_a?(Hash)
    problems << "#{task}: active.yaml missing or unparseable"
    next
  end
  rev = active["active_revision"].to_s
  asha = active["active_sha256"].to_s
  contract = File.join(dir, "contract.r#{rev}.yaml")
  if File.file?(contract)
    fsha = Digest::SHA256.file(contract).hexdigest
    problems << "#{task}: contract.r#{rev}.yaml hashes to #{short[fsha]} but active_sha256 is #{short[asha]}" if fsha != asha
    ok = Array(active["approvals"]).any? do |a|
      a.is_a?(Hash) && a["revision"].to_s == rev && a["sha256"].to_s == fsha &&
        !a["approved_by"].to_s.strip.empty? && !a["evidence"].to_s.strip.empty?
    end
    problems << "#{task}: no approval with approved_by + evidence for r#{rev} at file hash #{short[fsha]}" unless ok
  else
    problems << "#{task}: contract.r#{rev}.yaml missing"
  end
  rrev = report["contract_revision"].to_s
  problems << "#{task}: report is for r#{rrev} but r#{rev} is active" if rrev != rev
  rsha = report["contract_sha256_checked"].to_s
  problems << "#{task}: report checked #{short[rsha]} but active_sha256 is #{short[asha]}" if rsha != asha
end
exit 0 if problems.empty?

reason = "DONE is not supported: #{problems.join('; ')}. Fix the cause, or write a new report in " \
         ".done/<task>/reports/ with status NEEDS_REVIEW. Do not edit the contract or active.yaml to pass this gate."
puts JSON.generate("decision" => "block", "reason" => reason)
