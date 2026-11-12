import React from 'react';
import classNames from 'classnames';

/**
 * Simple white card container with padding and rounded corners.
 * Additional className will be merged.
 */
export function Card({ className, children, ...props }) {
  return (
    <div
      className={classNames('bazhi-card bg-white rounded-xl border border-gray-200 shadow-sm p-5', className)}
      {...props}
    >
      {children}
    </div>
  );
}

// also provide default export for backwards compatibility
export default Card;
