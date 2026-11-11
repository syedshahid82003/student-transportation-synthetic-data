export default function MappingNote() {
  return (
    <div className="mapping-note">
      <strong>Event type mapping</strong> (validator enum limits): &nbsp;
      <code>boarded</code> = present &nbsp;|&nbsp;
      <code>absent</code> = absent &nbsp;|&nbsp;
      <code>no_show</code> = missed pickup (route cancelled) &nbsp;|&nbsp;
      <code>late_pickup</code> = capacity-reduced ride (replaces boarded; notes field carries &quot;capacity_reduced&quot;)
    </div>
  )
}
