import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface HealthTimelineProps {
  /** 12 hourly failure-risk points (0-100), hour +1 through +12. Inverted to a
   * projected health score (100 − risk) for display so the chart reads the same
   * direction as the gauge: higher = healthier. */
  timeline: number[]
}

const CRITICAL_COLOR = '#f43f6e' // critical-500
const WARNING_COLOR = '#f59e0b' // warning/amber-500
const HEALTHY_COLOR = '#10b981' // healthy-500

/** Color a single bar by its projected health level (higher = healthier). */
function healthColor(value: number): string {
  if (value > 60) return HEALTHY_COLOR
  if (value > 30) return WARNING_COLOR
  return CRITICAL_COLOR
}

/**
 * 12-point hourly projected-health timeline (Requirement 14.2). Each bar is the
 * projected health score (100 − failure risk, 0-100) at that hour ahead, colored
 * green/amber/red by level so it matches the gauge's higher-is-healthier framing.
 */
export default function HealthTimeline({ timeline }: HealthTimelineProps) {
  const data = timeline.map((risk, index) => ({
    hour: `+${index + 1}h`,
    value: Math.round((100 - risk) * 10) / 10,
  }))

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 18, right: 8, bottom: 0, left: 8 }}>
        <XAxis
          dataKey="hour"
          tick={{ fill: '#475569', fontSize: 10 }}
          axisLine={{ stroke: '#e2e8f0' }}
          tickLine={false}
          interval={0}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: '#475569', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={28}
          tickFormatter={(v: number) => `${v}`}
        />
        <Tooltip
          cursor={{ fill: 'rgba(15,23,42,0.04)' }}
          contentStyle={{
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: '#475569' }}
          formatter={(value: number) => [`${value}% health`, 'Projected health']}
        />
        <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={40}>
          {data.map((entry) => (
            <Cell key={entry.hour} fill={healthColor(entry.value)} />
          ))}
          <LabelList
            dataKey="value"
            position="top"
            formatter={(value: number) => `${value}`}
            fill="#475569"
            fontSize={9}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
