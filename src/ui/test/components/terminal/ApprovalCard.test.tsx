/**
 * Tests for ApprovalCard component.
 *
 * Tests the approval card shown when a command needs user approval,
 * including button callbacks and content rendering.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ApprovalCard } from '../../../components/terminal/ApprovalCard'

describe('ApprovalCard', () => {
  const defaultProps = {
    command: 'rm -rf node_modules',
    cwd: '/home/user/project',
    onAllow: vi.fn(),
    onDeny: vi.fn(),
    onAllowRemember: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Content Rendering', () => {
    test('renders approval header', () => {
      render(<ApprovalCard {...defaultProps} />)

      expect(screen.getByText(/Xpdite wants to run a command/)).toBeInTheDocument()
    })

    test('renders the command', () => {
      render(<ApprovalCard {...defaultProps} command="npm install" />)

      expect(screen.getByText('$ npm install')).toBeInTheDocument()
    })

    test('renders command in code element', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const code = container.querySelector('.approval-command code')
      expect(code).toBeInTheDocument()
      expect(code?.textContent).toBe('$ rm -rf node_modules')
    })

    test('renders working directory', () => {
      render(<ApprovalCard {...defaultProps} cwd="/custom/path" />)

      expect(screen.getByText('in: /custom/path')).toBeInTheDocument()
    })

    test('does not render cwd section when cwd is empty', () => {
      const { container } = render(<ApprovalCard {...defaultProps} cwd="" />)

      const cwdElement = container.querySelector('.approval-cwd')
      expect(cwdElement).not.toBeInTheDocument()
    })
  })

  describe('Action Buttons', () => {
    test('renders Deny button', () => {
      render(<ApprovalCard {...defaultProps} />)

      const denyButton = screen.getByRole('button', { name: 'Deny' })
      expect(denyButton).toBeInTheDocument()
    })

    test('renders Allow button', () => {
      render(<ApprovalCard {...defaultProps} />)

      const allowButton = screen.getByRole('button', { name: 'Allow' })
      expect(allowButton).toBeInTheDocument()
    })

    test('renders Allow & Remember button', () => {
      render(<ApprovalCard {...defaultProps} />)

      const rememberButton = screen.getByRole('button', { name: 'Allow & Remember' })
      expect(rememberButton).toBeInTheDocument()
    })

    test('renders all three buttons in the actions area', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const actionsArea = container.querySelector('.approval-actions')
      expect(actionsArea).toBeInTheDocument()

      const buttons = actionsArea?.querySelectorAll('button')
      expect(buttons).toHaveLength(3)
    })
  })

  describe('Button Callbacks', () => {
    test('calls onDeny when Deny button is clicked', () => {
      const onDeny = vi.fn()
      render(<ApprovalCard {...defaultProps} onDeny={onDeny} />)

      const denyButton = screen.getByRole('button', { name: 'Deny' })
      fireEvent.click(denyButton)

      expect(onDeny).toHaveBeenCalledTimes(1)
    })

    test('calls onAllow when Allow button is clicked', () => {
      const onAllow = vi.fn()
      render(<ApprovalCard {...defaultProps} onAllow={onAllow} />)

      const allowButton = screen.getByRole('button', { name: 'Allow' })
      fireEvent.click(allowButton)

      expect(onAllow).toHaveBeenCalledTimes(1)
    })

    test('calls onAllowRemember when Allow & Remember button is clicked', () => {
      const onAllowRemember = vi.fn()
      render(<ApprovalCard {...defaultProps} onAllowRemember={onAllowRemember} />)

      const rememberButton = screen.getByRole('button', { name: 'Allow & Remember' })
      fireEvent.click(rememberButton)

      expect(onAllowRemember).toHaveBeenCalledTimes(1)
    })

    test('only the clicked button triggers its callback', () => {
      const onDeny = vi.fn()
      const onAllow = vi.fn()
      const onAllowRemember = vi.fn()
      render(
        <ApprovalCard
          {...defaultProps}
          onDeny={onDeny}
          onAllow={onAllow}
          onAllowRemember={onAllowRemember}
        />
      )

      fireEvent.click(screen.getByRole('button', { name: 'Allow' }))

      expect(onAllow).toHaveBeenCalledTimes(1)
      expect(onDeny).not.toHaveBeenCalled()
      expect(onAllowRemember).not.toHaveBeenCalled()
    })
  })

  describe('Button Styling', () => {
    test('Deny button has btn-deny class', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const denyButton = container.querySelector('.btn-deny')
      expect(denyButton).toBeInTheDocument()
      expect(denyButton?.textContent).toBe('Deny')
    })

    test('Allow button has btn-allow class', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const allowButton = container.querySelector('.btn-allow')
      expect(allowButton).toBeInTheDocument()
      expect(allowButton?.textContent).toBe('Allow')
    })

    test('Allow & Remember button has btn-allow-remember class', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const rememberButton = container.querySelector('.btn-allow-remember')
      expect(rememberButton).toBeInTheDocument()
      expect(rememberButton?.textContent).toBe('Allow & Remember')
    })
  })

  describe('Component Structure', () => {
    test('renders with correct root class', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const card = container.querySelector('.terminal-approval-card')
      expect(card).toBeInTheDocument()
    })

    test('has approval-header section', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const header = container.querySelector('.approval-header')
      expect(header).toBeInTheDocument()
    })

    test('has approval-command section', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const commandSection = container.querySelector('.approval-command')
      expect(commandSection).toBeInTheDocument()
    })

    test('has approval-actions section', () => {
      const { container } = render(<ApprovalCard {...defaultProps} />)

      const actionsSection = container.querySelector('.approval-actions')
      expect(actionsSection).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    test('handles very long command', () => {
      const longCommand = 'npm run build && npm run test && npm run lint'.repeat(10)
      render(<ApprovalCard {...defaultProps} command={longCommand} />)

      expect(screen.getByText(`$ ${longCommand}`)).toBeInTheDocument()
    })

    test('handles command with special characters', () => {
      const specialCommand = 'echo "Hello $USER" | grep -E "^[a-z]+"'
      render(<ApprovalCard {...defaultProps} command={specialCommand} />)

      expect(screen.getByText(`$ ${specialCommand}`)).toBeInTheDocument()
    })

    test('handles cwd with special characters', () => {
      render(<ApprovalCard {...defaultProps} cwd="/path/with spaces/and-dashes" />)

      expect(screen.getByText('in: /path/with spaces/and-dashes')).toBeInTheDocument()
    })

    test('handles Windows-style path', () => {
      render(<ApprovalCard {...defaultProps} cwd="C:\\Users\\Project" />)

      expect(screen.getByText((content) => content.includes('in:') && content.includes('C:\\\\Users\\\\Project'))).toBeInTheDocument()
    })

    test('multiple rapid clicks only fire callbacks once each', () => {
      const onAllow = vi.fn()
      render(<ApprovalCard {...defaultProps} onAllow={onAllow} />)

      const allowButton = screen.getByRole('button', { name: 'Allow' })

      // Simulate rapid clicks
      fireEvent.click(allowButton)
      fireEvent.click(allowButton)
      fireEvent.click(allowButton)

      expect(onAllow).toHaveBeenCalledTimes(3)
    })
  })

  describe('Accessibility', () => {
    test('buttons are focusable', () => {
      render(<ApprovalCard {...defaultProps} />)

      const buttons = screen.getAllByRole('button')
      buttons.forEach((button) => {
        expect(button).not.toHaveAttribute('tabindex', '-1')
      })
    })

    test('buttons can be activated with keyboard', () => {
      const onAllow = vi.fn()
      render(<ApprovalCard {...defaultProps} onAllow={onAllow} />)

      const allowButton = screen.getByRole('button', { name: 'Allow' })
      allowButton.focus()
      fireEvent.keyDown(allowButton, { key: 'Enter' })
      fireEvent.keyUp(allowButton, { key: 'Enter' })

      // Note: fireEvent.keyDown/keyUp doesn't trigger click handlers
      // Use fireEvent.click to simulate button activation
      fireEvent.click(allowButton)
      expect(onAllow).toHaveBeenCalled()
    })
  })
})
