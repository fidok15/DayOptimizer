import { useState } from "react";
import { MotionConfig, motion } from "motion/react";
import Skyline from "./scene/Skyline";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import Calendar from "./components/Calendar";
import Footer from "./components/Footer";
import { LoadError, LoadingSkeleton } from "./components/States";
import { usePlanner } from "./lib/usePlanner";
import { WEEKDAYS, type View, type Weekday } from "./lib/types";

const todayKey = (): Weekday => WEEKDAYS[(new Date().getDay() + 6) % 7];
const rise = (i: number) => ({
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { type: "spring" as const, stiffness: 120, damping: 20, delay: i * 0.08 },
});

export default function App() {
  const p = usePlanner();
  const [view, setView] = useState<View>(() => (window.innerWidth < 768 ? "day" : "week"));
  const [day, setDay] = useState<Weekday>(todayKey);

  return (
    <MotionConfig reducedMotion="user">
      <Skyline />
      <div className="relative mx-auto flex min-h-[100dvh] max-w-[1400px] flex-col gap-5 px-4 py-5 md:px-8 md:py-8">
        <motion.div {...rise(0)} className="relative z-50">
          <Header
            view={view}
            onViewChange={setView}
            saveStatus={p.saveStatus}
            saveError={p.saveError}
            onRetry={p.retrySave}
            categories={p.categories}
            onImport={p.importBlocks}
            day={day}
          />
        </motion.div>

        {p.load === "loading" && <LoadingSkeleton />}
        {p.load === "error" && <LoadError message={p.loadError} onRetry={p.reload} />}
        {p.load === "ready" && (
          <main className="grid flex-1 grid-cols-1 gap-5 lg:grid-cols-[20rem_1fr]">
            <motion.div {...rise(1)} className="order-2 min-w-0 lg:order-none">
              <Sidebar
                categories={p.categories}
                week={p.week}
                defaults={p.defaults}
                onChange={p.updateCategories}
                onRemove={p.removeCategory}
              />
            </motion.div>
            <motion.div {...rise(2)} className="min-w-0">
              <Calendar
                view={view}
                week={p.week}
                categories={p.categories}
                day={day}
                onDayChange={setDay}
                onChange={p.updateWeek}
                dayStart={p.dayStart}
              />
            </motion.div>
          </main>
        )}

        <Footer />
      </div>
    </MotionConfig>
  );
}
