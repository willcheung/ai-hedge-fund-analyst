/** Presentation only: never remove substantive paragraphs or exceptional hours. */
export const isMarketSetupHeading = (text: string) => /^market setup$/i.test(text.trim())
export function morningBriefProse(text: string): string {
  let fence = ''
  return text.split('\n').map(line => {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)
    if (marker) {
      if (!fence) fence = marker[1]
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length && line.trim() === marker[1]) fence = ''
      return line
    }
    if (fence) return line
    // Leave lines containing protected inline source intact; this editorial
    // projection only simplifies ordinary prose and bold snapshot copy.
    if (/[`\[<]/.test(line)) return line
    if (/^\s*#{1,6}\s+market setup\s*#*\s*$/i.test(line)) return ''
    // A complete routine sentence only. Commas/semicolons and other clauses
    // intentionally prevent a match, preserving holiday and special-hour context.
    return line.replace(/(^|(?<!U\.S)[.!?]\s+)(?:U\.S\.\s+)?(?:cash trading|cash market|US cash trading) opens (?:at )?09:30 ET\.(?=\s|\*\*$|$)\s*/gi, (match, boundary: string, offset: number) => line.slice(offset + match.length).startsWith('**') ? boundary.trimEnd() : boundary)
  }).join('\n')
}
